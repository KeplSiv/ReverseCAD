import Foundation
import AVFoundation
import ARKit
import ReverseCADCore

/// Records capabilities separately from the sensors this build actually activates.
enum CaptureHardware {
    static func report() -> [String:Any] {
        let discovery=AVCaptureDevice.DiscoverySession(deviceTypes:[.builtInWideAngleCamera,.builtInUltraWideCamera,.builtInTelephotoCamera,.builtInTrueDepthCamera],mediaType:.video,position:.unspecified)
        return ["active_path":"public_arkit_primary_camera_native_depth",
                "configured_rear_camera_count":ARWorldTrackingConfiguration.isSupported ? 1 : 0,"all_three_rear_cameras_active":false,
                "private_sensor_interception_active":false,
                "scene_depth_supported":ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth),
                "available_camera_types":discovery.devices.map{$0.deviceType.rawValue},
                "multicam_supported":AVCaptureMultiCamSession.isMultiCamSupported,
                "supported_multicam_sets":discovery.supportedMultiCamDeviceSets.map{$0.map{$0.deviceType.rawValue}.sorted()},
                "rear_calibration":"factory_per_frame; fitted corrections unvalidated"]
    }
    static func preserveReference(_ archivePath: String,in directory: URL,profileURL: URL? = nil) throws {
        let archive=URL(fileURLWithPath:archivePath)
        let bytes=(try archive.resourceValues(forKeys:[.fileSizeKey])).fileSize ?? 0
        guard bytes>0,bytes<=64*1024*1024 else {throw ServiceFailure(message:"The reference archive is missing or exceeds 64 MiB. Capture a new front reference.")}
        let currentProfile=profileURL ?? FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("PhoneCalibrationProfiles/current.json")
        let profile=try JSONDecoder().decode(PhoneCalibrationProfile.self,from:Data(contentsOf:currentProfile))
        guard profile.referenceArchiveSHA256 == (try CaptureIO.sha256(file:archive)) else {throw ServiceFailure(message:"This reference no longer matches the phone setup. Capture a new reference.")}
        let target=directory.appendingPathComponent("calibration/reference.zip")
        try FileManager.default.createDirectory(at:target.deletingLastPathComponent(),withIntermediateDirectories:true)
        if !FileManager.default.fileExists(atPath:target.path) {try FileManager.default.copyItem(at:archive,to:target)}
        guard try CaptureIO.sha256(file:target)==CaptureIO.sha256(file:archive) else {throw ServiceFailure(message:"The saved reference copy does not match its original.")}
        let data=try JSONSerialization.data(withJSONObject:report(),options:[.sortedKeys])
        try data.write(to:directory.appendingPathComponent("capture-hardware.json"),options:.atomic)
    }
}
