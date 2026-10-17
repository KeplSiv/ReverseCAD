import Foundation
import ARKit
import RealityKit
import UIKit
import simd

struct LiveGeometrySnapshot: Codable, Sendable {
    var session_id: String
    var sequence: Int
    var vertices: [[Double]]
    var triangles: [[Int]]
    var camera_positions: [[Double]]
    var unit = "m"
}

struct LiveGhostResponse: Codable {
    struct Candidate: Codable, Identifiable, Equatable {
        var id: String
        var method: String
        var mesh: MeshPreview
        var support_score: Double
        var assumptions: [String]
        var worldPositions: [SIMD3<Float>] { mesh.vertices.map { SIMD3<Float>(Float($0[0]/1000),Float($0[1]/1000),Float($0[2]/1000)) } }
    }
    var session_id: String
    var sequence: Int
    var status: String
    var message: String
    var candidates: [Candidate]
}

/// A response may only draw in the uninterrupted AR coordinate frame that sent it.
/// Late responses, tracking resets and object re-selection cannot revive old ghosts.
struct GhostLifecycle {
    var sessionID = UUID().uuidString
    var lastSequence = -1
    var candidates: [LiveGhostResponse.Candidate] = []
    var selectedIndex = 0
    var expiresAt = Date.distantPast
    var selected: LiveGhostResponse.Candidate? {
        candidates.indices.contains(selectedIndex) ? candidates[selectedIndex] : nil
    }
    mutating func reset() {
        sessionID = UUID().uuidString; lastSequence = -1
        candidates = []; selectedIndex = 0; expiresAt = .distantPast
    }
    @discardableResult mutating func accept(_ response: LiveGhostResponse, now: Date, sentAt: Date) -> Bool {
        guard response.session_id == sessionID, response.sequence > lastSequence,
              now.timeIntervalSince(sentAt) < 24, response.status == "provisional" || response.candidates.isEmpty else { return false }
        guard response.candidates.allSatisfy({ candidate in
            let m = candidate.mesh
            return m.unit == "mm" && !m.vertices.isEmpty && m.vertices.count <= 8000 && !m.triangles.isEmpty && m.triangles.count <= 12000 &&
                m.vertices.allSatisfy { $0.count == 3 && $0.allSatisfy { $0.isFinite && abs($0) < 100_000 } } &&
                m.triangles.allSatisfy { $0.count == 3 && Set($0).count == 3 && $0.allSatisfy { m.vertices.indices.contains($0) } }
        }) else { return false }
        lastSequence = response.sequence; candidates = response.candidates; selectedIndex = 0
        expiresAt = now.addingTimeInterval(16)
        return true
    }
    mutating func expire(at now: Date) {
        if now >= expiresAt { candidates = []; selectedIndex = 0 }
    }
    mutating func next() { if !candidates.isEmpty { selectedIndex = (selectedIndex + 1) % candidates.count } }
}

extension ARKitCaptureProvider {
    /// Filter the scene mesh by this frame's foreground mask AND measured depth.
    /// No cuboid proxy, fixed object width, or arbitrary triangle subsampling.
    static func objectSnapshot(anchors: [ARMeshAnchor], pose: simd_float4x4, intrinsics: simd_float3x3,
                               imageSize: CGSize, depth: Data, mask: Data, confidence: Data,
                               width: Int, height: Int, sessionID: String, sequence: Int,
                               cameras: [[Double]]) -> LiveGeometrySnapshot? {
        guard width > 0, height > 0, depth.count == width*height*4, mask.count == width*height,
              confidence.count == width*height, cameras.count >= 3 else { return nil }
        let inverse = simd_inverse(pose)
        var vertices: [[Double]] = []; var triangles: [[Int]] = []
        for anchor in anchors {
            let geometry = anchor.geometry
            guard geometry.faces.indexCountPerPrimitive == 3, geometry.faces.bytesPerIndex == 4 else { continue }
            var remap = [Int](repeating: -1, count: geometry.vertices.count)
            for i in 0..<geometry.vertices.count {
                let ptr = geometry.vertices.buffer.contents().advanced(by: geometry.vertices.offset + geometry.vertices.stride*i)
                let p = SIMD3<Float>(ptr.loadUnaligned(as: Float.self), ptr.advanced(by: 4).loadUnaligned(as: Float.self), ptr.advanced(by: 8).loadUnaligned(as: Float.self))
                let world = anchor.transform * SIMD4<Float>(p,1)
                let local = inverse * world
                guard local.z < -0.03 else { continue }
                let pixel = intrinsics * SIMD3<Float>(local.x,-local.y,-local.z)
                let x = Int(pixel.x / pixel.z / Float(imageSize.width) * Float(width))
                let y = Int(pixel.y / pixel.z / Float(imageSize.height) * Float(height))
                guard x >= 0, y >= 0, x < width, y < height else { continue }
                let index = y*width+x
                guard mask[index] != 0, confidence[index] >= 1 else { continue }
                let measured = depth.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: index*4, as: Float.self) }
                guard measured.isFinite, measured > 0, abs(measured+local.z) < max(0.008,measured*0.03) else { continue }
                remap[i] = vertices.count; vertices.append([Double(world.x),Double(world.y),Double(world.z)])
                if vertices.count > 8000 { return nil }
            }
            for i in 0..<geometry.faces.count {
                let indices = geometry.faces.buffer.contents().advanced(by: i*3*4).assumingMemoryBound(to: UInt32.self)
                let raw = [Int(indices[0]),Int(indices[1]),Int(indices[2])]
                guard raw.allSatisfy({ remap.indices.contains($0) && remap[$0] >= 0 }) else { continue }
                triangles.append(raw.map { remap[$0] })
                if triangles.count > 12000 { return nil }
            }
        }
        guard triangles.count >= 100 else { return nil }
        // Remove unused vertices without opening holes by dropping triangles.
        let used = Set(triangles.flatMap { $0 }).sorted()
        var mapping: [Int:Int] = [:]
        for (i,old) in used.enumerated() { mapping[old] = i }
        let compact = used.map { vertices[$0] }
        let extents = (0..<3).map { axis in compact.map { $0[axis] }.max()! - compact.map { $0[axis] }.min()! }
        guard let size = extents.max(), size >= 0.005, size <= 1 else { return nil }
        return LiveGeometrySnapshot(session_id: sessionID, sequence: sequence, vertices: compact,
            triangles: triangles.map { $0.map { mapping[$0]! } }, camera_positions: Array(cameras.suffix(24)))
    }
}
