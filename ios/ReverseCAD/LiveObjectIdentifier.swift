import ARKit
import CoreImage
import CryptoKit
import SwiftUI
import ReverseCADCore

struct ObjectCameraSnapshot {
    let jpeg: Data
    let pose: simd_float4x4
    let frameTimestamp: TimeInterval
    let capturedAt: TimeInterval
    var hash: String { SHA256.hash(data: jpeg).map { String(format: "%02x", $0) }.joined() }

    func matches(_ frame: ARFrame, maximumAge: TimeInterval = LiveIdentificationSchedule.maximumAge) -> Bool {
        let age = ProcessInfo.processInfo.systemUptime - capturedAt
        let distance = simd_distance(pose.columns.3, frame.camera.transform.columns.3)
        // Compare all camera axes, including roll, before reusing image coordinates.
        let rotation = (0..<3).map { index -> Float in
            let a = pose[index], b = frame.camera.transform[index]
            return simd_dot(SIMD3(a.x, a.y, a.z), SIMD3(b.x, b.y, b.z))
        }.min() ?? 0
        return age >= 0 && age <= maximumAge && distance < 0.025 && rotation > 0.995
    }
}

struct IdentifiedObject {
    let snapshot: ObjectCameraSnapshot
    let box: CGRect // Normalized top-left coordinates in the portrait JPEG.
    let response: [String: Any]
    var rawBox: CGRect { CGRect(x: box.minY, y: 1-box.maxX, width: box.height, height: box.width) }
    var label: String {
        let category = response["category"] as? String ?? "object"
        return category.replacingOccurrences(of: "_", with: " ").capitalized
    }
}

/// Continuously queries Jev on new frames. Network work overlaps but never builds a frame queue.
@MainActor final class LiveObjectIdentifier: ObservableObject {
    @Published private(set) var candidate: IdentifiedObject?
    @Published private(set) var message = "Jev is looking for your object…"
    @Published private(set) var running = false
    private let context = CIContext()
    private var schedule = LiveIdentificationSchedule()
    private var loop: Task<Void, Never>?
    private var requests: [UUID: Task<Void, Never>] = [:]
    private var lastFrameTimestamp: TimeInterval = -1

    func snapshot(_ frame: ARFrame) throws -> ObjectCameraSnapshot {
        let source = CIImage(cvPixelBuffer: frame.capturedImage).oriented(.right)
        let scale = min(1, 640 / max(source.extent.width, source.extent.height))
        let image = source.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        guard min(image.extent.width, image.extent.height) >= 280,
              let cg = context.createCGImage(image, from: image.extent),
              let jpeg = UIImage(cgImage: cg).jpegData(compressionQuality: 0.8) else {
            throw ServiceFailure(message: "Could not read the camera image.")
        }
        return ObjectCameraSnapshot(jpeg: jpeg, pose: frame.camera.transform, frameTimestamp: frame.timestamp,
                                    capturedAt: ProcessInfo.processInfo.systemUptime)
    }

    func start(session: ARSession, description: String, model: AppModel) {
        stop(); running = true; message = "Jev is looking for your object…"
        schedule.start(at: ProcessInfo.processInfo.systemUptime)
        loop = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, self.running else { return }
                self.tick(session: session, description: description, model: model)
                try? await Task.sleep(for: .milliseconds(20))
            }
        }
    }

    func stop() {
        running = false; schedule.stop(); loop?.cancel(); loop = nil
        for request in requests.values { request.cancel() }
        requests.removeAll(); candidate = nil; lastFrameTimestamp = -1
    }

    func currentCandidate(session: ARSession) -> IdentifiedObject? {
        guard let candidate, let frame = session.currentFrame, candidate.snapshot.matches(frame) else { return nil }
        return candidate
    }

    private func tick(session: ARSession, description: String, model: AppModel) {
        let now = ProcessInfo.processInfo.systemUptime
        if candidate != nil && currentCandidate(session: session) == nil { candidate = nil }
        guard let frame = session.currentFrame, frame.timestamp != lastFrameTimestamp,
              let ticket = schedule.reserve(at: now) else { return }
        lastFrameTimestamp = frame.timestamp
        let photo: ObjectCameraSnapshot
        do { photo = try snapshot(frame) }
        catch {
            _ = schedule.complete(ticket, at: now); schedule.failed(at: now)
            message = error.localizedDescription; return
        }
        requests[ticket.id] = Task { [weak self] in
            guard let self else { return }
            defer { self.requests.removeValue(forKey: ticket.id) }
            var ownsLatestReply = false
            do {
                let id = ticket.id.uuidString
                let response = try await model.object("v1/objects/identify", method: "POST", json: [
                    "description": description, "image_base64": photo.jpeg.base64EncodedString(), "request_id": id
                ])
                guard !Task.isCancelled,
                      self.schedule.complete(ticket, at: ProcessInfo.processInfo.systemUptime) else { return }
                ownsLatestReply = true
                guard response["request_id"] as? String == id, response["image_sha256"] as? String == photo.hash else {
                    throw ServiceFailure(message: "Jev returned a reply for a different image. Retrying…")
                }
                self.schedule.succeeded()
                guard let current = session.currentFrame, photo.matches(current) else {
                    self.candidate = nil; self.message = "Keep the object in view while Jev catches up."; return
                }
                guard response["status"] as? String == "confirm_target",
                      let edges = response["box"] as? [String: Double],
                      let top = edges["top"], let bottom = edges["bottom"],
                      let left = edges["left"], let right = edges["right"],
                      [top,bottom,left,right].allSatisfy({ $0.isFinite && (0...1).contains($0) }),
                      bottom > top, right > left else {
                    self.candidate = nil; self.message = "Show one whole object matching your description."; return
                }
                self.candidate = IdentifiedObject(snapshot: photo, box: CGRect(x: left, y: top, width: right-left, height: bottom-top), response: response)
                self.message = "Jev is updating the outline live."
            } catch {
                guard !Task.isCancelled else { return }
                // A failed old reply must not erase a newer good detection.
                if ownsLatestReply || self.schedule.complete(ticket, at: ProcessInfo.processInfo.systemUptime, includingExpired: true) {
                    self.candidate = nil; self.message = "Jev is reconnecting. Check the Mac connection if this continues."
                    self.schedule.failed(at: ProcessInfo.processInfo.systemUptime)
                }
            }
        }
    }
}

struct LiveObjectOverlay: View {
    @ObservedObject var identifier: LiveObjectIdentifier
    let session: ARSession
    var body: some View {
        GeometryReader { geometry in
            TimelineView(.periodic(from: .now, by: 0.05)) { _ in
                if let candidate = identifier.currentCandidate(session: session), let frame = session.currentFrame {
                    let transform = frame.displayTransform(for: .portrait, viewportSize: geometry.size)
                    let rect = candidate.rawBox.applying(transform)
                        .applying(CGAffineTransform(scaleX: geometry.size.width, y: geometry.size.height))
                    Rectangle().stroke(.mint, lineWidth: 3)
                        .frame(width: rect.width, height: rect.height).position(x: rect.midX, y: rect.midY)
                    Text(candidate.label).font(.caption.bold()).padding(7).background(.mint, in: Capsule())
                        .foregroundStyle(.black).position(x: min(max(rect.midX, 70), max(70, geometry.size.width-70)), y: max(18, rect.minY-18))
                }
            }
        }.allowsHitTesting(false).accessibilityLabel("Live Jev object outline")
    }
}
