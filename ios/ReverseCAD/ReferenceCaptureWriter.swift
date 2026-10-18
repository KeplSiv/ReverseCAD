// Reused from Frankly; original buffers and per-frame metadata remain immutable.
import Foundation
import AVFoundation
import ARKit
import CoreImage
import CryptoKit
import UIKit
import simd

func cameraRows(_ m: simd_float3x3) -> [[Double]] { (0..<3).map { r in (0..<3).map { c in Double(m[c][r]) } } }
func cameraRows(_ m: simd_float4x4) -> [[Double]] { (0..<4).map { r in (0..<4).map { c in Double(m[c][r]) } } }
func cameraJSONWrite(_ value: Any, _ url: URL) throws {
    // Dropped synchronized samples may carry invalid CMTime values (NaN).
    // NSJSONSerialization raises an Objective-C exception for those, which a
    // Swift catch cannot intercept. Represent unavailable numbers as JSON null.
    func safe(_ item:Any) -> Any {
        if let dict=item as? [String:Any] {return dict.mapValues{safe($0)}}
        if let array=item as? [Any] {return array.map{safe($0)}}
        if let number=item as? NSNumber, !number.doubleValue.isFinite {return NSNull()}
        return item
    }
    let object=safe(value)
    guard JSONSerialization.isValidJSONObject(object) else {throw CameraLabError.message("Capture metadata contains an unsupported JSON value")}
    let data = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
    try data.write(to: url, options: .atomic)
}
enum CameraLabError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let s) = self { return s }; return nil }
}

final class ExperimentWriter {
    let url: URL
    let source: String
    var experimentContext: [String: Any] = [:]
    var photos = [[String: Any]]()
    var directDepth = [[String: Any]]()
    var frames = [[String: Any]]()
    var pairs = [[String: Any]]()
    var lidar = [[String: Any]]()
    var events = [[String: Any]]()
    var measurement = [String: Any]()
    private var completed = false
    private let context = CIContext(options: [.cacheIntermediates: false])
    init(source: String = "physical_iphone_capture") throws {
        self.source = source
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("CameraExperiments", isDirectory: true)
        let name = "capture-" + ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
        url = docs.appendingPathComponent(name + "-" + UUID().uuidString.prefix(6), isDirectory: true)
        try FileManager.default.createDirectory(at: url.appendingPathComponent("frames"), withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: url.appendingPathComponent("lidar"), withIntermediateDirectories: true)
    }
    func event(_ name: String, _ info: [String: Any] = [:]) { events.append(["name": name, "uptime_s": ProcessInfo.processInfo.systemUptime, "details": info]) }
    func checkpoint(_ capabilities: [String: Any], complete: Bool = false) throws {
        completed = completed || complete
        try cameraJSONWrite(capabilities, url.appendingPathComponent("capabilities.json"))
        try cameraJSONWrite(["schema": "stationary-stereo/1", "source": source, "complete": completed,
                       "coordinate_convention": "OpenCV optical: x right, y down, z forward; translations meters unless explicitly suffixed _mm",
                       "rgb_buffer_kind": "delivered processed CVPixelBuffer, NOT RAW sensor data",
                       "pairs": pairs, "frames": frames, "lidar": lidar, "events": events, "experiment": experimentContext, "photos": photos, "raw_photos": photos.filter { $0["is_raw"] as? Bool == true }, "av_depth": directDepth,
                       "measurement": measurement,
                       "calibration": NSNull(), "reference_registration": NSNull()], url.appendingPathComponent("session.json"))
        let files = try FileManager.default.subpathsOfDirectory(atPath: url.path).filter { $0 != "manifest.json" }
        var manifest = [[String: Any]]()
        for file in files.sorted() {
            let path = url.appendingPathComponent(file)
            var directory: ObjCBool = false
            if FileManager.default.fileExists(atPath: path.path, isDirectory: &directory), !directory.boolValue {
                let d = try Data(contentsOf: path)
                manifest.append(["path": file, "bytes": d.count, "sha256": SHA256.hash(data: d).map { String(format: "%02x", $0) }.joined()])
            }
        }
        try cameraJSONWrite(["algorithm": "sha256", "files": manifest], url.appendingPathComponent("manifest.json"))
    }
    func png(_ buffer: CVPixelBuffer, path: String) throws {
        try context.writePNGRepresentation(of: CIImage(cvPixelBuffer: buffer), to: url.appendingPathComponent(path), format: .RGBA8, colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!)
    }
    func original(_ buffer: CVPixelBuffer, stem: String) throws -> [String: Any] {
        CVPixelBufferLockBaseAddress(buffer, .readOnly); defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        let n = CVPixelBufferGetPlaneCount(buffer)
        var planes = [[String: Any]]()
        for i in 0..<max(1, n) {
            let h = n == 0 ? CVPixelBufferGetHeight(buffer) : CVPixelBufferGetHeightOfPlane(buffer, i)
            let w = n == 0 ? CVPixelBufferGetWidth(buffer) : CVPixelBufferGetWidthOfPlane(buffer, i)
            let stride = n == 0 ? CVPixelBufferGetBytesPerRow(buffer) : CVPixelBufferGetBytesPerRowOfPlane(buffer, i)
            let base = n == 0 ? CVPixelBufferGetBaseAddress(buffer) : CVPixelBufferGetBaseAddressOfPlane(buffer, i)
            guard let base else { throw CameraLabError.message("Missing pixel-buffer base address") }
            let file = "\(stem)-plane\(i).bin"
            try Data(bytes: base, count: stride * h).write(to: url.appendingPathComponent(file), options: .atomic)
            planes.append(["file": file, "width": w, "height": h, "row_bytes": stride])
        }
        return ["pixel_format": CVPixelBufferGetPixelFormatType(buffer), "planes": planes, "width": CVPixelBufferGetWidth(buffer), "height": CVPixelBufferGetHeight(buffer), "endianness": "little", "preservation": "exact delivered buffer bytes including row padding; lossless archive", "attachments_description": String(describing: CVBufferCopyAttachments(buffer, .shouldPropagate))]
    }
    func save(_ sample: CMSampleBuffer, camera: String, settings: [String: Any]) throws -> String {
        guard let buffer = CMSampleBufferGetImageBuffer(sample) else { throw CameraLabError.message("Frame has no image") }
        let id = String(format: "%@-%05d", camera, frames.count)
        let path = "frames/\(id).png"
        try png(buffer, path: path)
        var frame: [String: Any] = ["id": id, "camera": camera, "rgb": path, "rgb_encoding": "lossless PNG; sRGB RGBA8 conversion of preserved original buffer", "timestamp_s": CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample)), "timestamp_clock": "CoreMedia host clock", "width": CVPixelBufferGetWidth(buffer), "height": CVPixelBufferGetHeight(buffer), "settings": settings, "rotation_degrees": 0, "mirrored": false, "original": try original(buffer, stem: "frames/\(id)"), "intrinsics": NSNull()]
        if let format=CMSampleBufferGetFormatDescription(sample) {
            let aperture=CMVideoFormatDescriptionGetCleanAperture(format,originIsAtTopLeft:true)
            frame["clean_aperture"]=[aperture.origin.x,aperture.origin.y,aperture.width,aperture.height]
        }
        frame["delivered_coordinate_transform"]=["rotation_degrees":settings["video_rotation_degrees"] ?? 0,"mirrored":settings["mirrored"] ?? false,"scale_crop_factor":settings["video_scale_and_crop_factor"] ?? 1]
        let stamp=CMSampleBufferGetPresentationTimeStamp(sample)
        frame["timestamp_rational"]=["value":stamp.value,"timescale":stamp.timescale,"epoch":stamp.epoch,"flags":stamp.flags.rawValue]
        frame["data_kind"]="losslessly stored processed video frame; not a photo or sensor RAW"
        frame["sample_attachments_description"]=String(describing:CMCopyDictionaryOfAttachments(allocator:kCFAllocatorDefault,target:sample,attachmentMode:kCMAttachmentMode_ShouldPropagate))
        frame["duration_s"]=CMTimeGetSeconds(CMSampleBufferGetDuration(sample)).isFinite ? CMTimeGetSeconds(CMSampleBufferGetDuration(sample)) : NSNull()
        frame["optical_processing_note"]="Geometric correction state is the public control readback. Residual ISP correction and OIS are not fully observable; fit only in these delivered coordinates."
        if let data = CMGetAttachment(sample, key: kCMSampleBufferAttachmentKey_CameraIntrinsicMatrix, attachmentModeOut: nil) as? Data, data.count >= MemoryLayout<simd_float3x3>.size {
            frame["intrinsics"] = cameraRows(data.withUnsafeBytes { $0.loadUnaligned(as: simd_float3x3.self) })
            frame["intrinsics_reference_size"] = [CVPixelBufferGetWidth(buffer), CVPixelBufferGetHeight(buffer)]
        }
        try cameraJSONWrite(frame, url.appendingPathComponent("frames/\(id).json"))
        frames.append(frame)
        return id
    }
    func saveDepth(_ frame: ARFrame, smoothed: Bool = false) throws {
        guard let depth = smoothed ? frame.smoothedSceneDepth : frame.sceneDepth else { return }
        let id = String(format: "ar-%04d", lidar.count)
        let rgb = "lidar/\(id).png"
        try png(frame.capturedImage, path: rgb)
        var entry: [String: Any] = ["id": id, "rgb": rgb, "timestamp_s": frame.timestamp, "timestamp_clock": "ARFrame system uptime", "reference_name": "iPhone LiDAR-derived depth", "depth_kind": "optical_axis_z", "units": "m", "application_filtering": false, "requested_smoothed_scene_depth": smoothed, "system_filtering": "ARKit-managed; not fully exposed", "source": smoothed ? "ARFrame.smoothedSceneDepth" : "ARFrame.sceneDepth; RGB-guided system processing may remain", "rgb_intrinsics": cameraRows(frame.camera.intrinsics), "rgb_size": [frame.camera.imageResolution.width, frame.camera.imageResolution.height], "T_world_arkit_camera": cameraRows(frame.camera.transform), "arkit_to_optical": [[1,0,0,0],[0,-1,0,0],[0,0,-1,0],[0,0,0,1]], "tracking": String(describing: frame.camera.trackingState), "rgb_original": try original(frame.capturedImage, stem: "lidar/\(id)-rgb"), "depth": try original(depth.depthMap, stem: "lidar/\(id)-depth")]
        if let c = depth.confidenceMap { entry["confidence"] = try original(c, stem: "lidar/\(id)-confidence") }
        try cameraJSONWrite(entry, url.appendingPathComponent("lidar/\(id).json"))
        lidar.append(entry)
    }
    func preview(_ buffer: CVPixelBuffer) -> UIImage? {
        let im = CIImage(cvPixelBuffer: buffer)
        let small = im.transformed(by: CGAffineTransform(scaleX: 480 / im.extent.width, y: 480 / im.extent.width))
        return context.createCGImage(small, from: small.extent).map { UIImage(cgImage: $0) }
    }
    func archive() throws -> URL {
        let dest = url.deletingLastPathComponent().appendingPathComponent(url.lastPathComponent + ".zip")
        var error: NSError?; var copiedError: Error?
        NSFileCoordinator().coordinate(readingItemAt: url, options: .forUploading, error: &error) { zipped in
            do { if FileManager.default.fileExists(atPath: dest.path) { try FileManager.default.removeItem(at: dest) }; try FileManager.default.copyItem(at: zipped, to: dest) } catch { copiedError = error }
        }
        if let error { throw error }; if let copiedError { throw copiedError }; return dest
    }

}
