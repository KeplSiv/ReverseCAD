#if DEBUG
import SwiftUI
import CoreImage
import ReverseCADCore

/// Runs the production capture path without marking phone setup as calibrated.
@MainActor final class MultiCameraValidation: ObservableObject {
    @Published var camera: MultiCameraSession?
    @Published var message="Starting all rear sensors…"
    private var capture:MultiCameraCaptureProvider?
    func start() async {
        let root=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("MultiCameraValidation/\(UUID().uuidString)")
        do {
            let session=MultiCameraSession();try await session.start();camera=session
            try await Task.sleep(for:.seconds(3))
            var mappings=[[String:Any]]()
            for angle:CGFloat in [0,90,180,270] {
                session.preview.connection?.videoRotationAngle=angle
                let rect=CGRect(x:session.preview.bounds.width/3,y:session.preview.bounds.height/3,width:session.preview.bounds.width/3,height:session.preview.bounds.height/3)
                let metadata=session.preview.metadataOutputRectConverted(fromLayerRect:rect)
                let video=try session.videoRegion(fromMetadata:metadata)
                guard video.minX>=0,video.minY>=0,video.maxX<=1.00001,video.maxY<=1.00001,video.width>0,video.height>0 else {throw ServiceFailure(message:"Camera framing did not map into normalized image coordinates.")}
                let recovered=session.preview.layerRectConverted(fromMetadataOutputRect:try session.metadataRegion(fromVideo:video))
                mappings.append(["angle":angle,"preview_rect":[rect.minX,rect.minY,rect.width,rect.height],"video_box":[video.minX,video.minY,video.width,video.height],"roundtrip_error_px":max(abs(recovered.minX-rect.minX),abs(recovered.minY-rect.minY),abs(recovered.width-rect.width),abs(recovered.height-rect.height))])
            }
            session.preview.connection?.videoRotationAngle=90
            if let video=session.latest(),let jpeg=CIContext().jpegRepresentation(of:CIImage(cvPixelBuffer:video.pixel),colorSpace:CGColorSpaceCreateDeviceRGB(),options:[:]) {
                try FileManager.default.createDirectory(at:root.deletingLastPathComponent(),withIntermediateDirectories:true)
                try jpeg.write(to:root.deletingLastPathComponent().appendingPathComponent(root.lastPathComponent+"-preview.jpg"))
            }
            let provider=try MultiCameraCaptureProvider(camera:session,directory:root,scanID:UUID().uuidString,region:CGRect(x:0.15,y:0.15,width:0.7,height:0.7),confirmed:false)
            capture=provider
            provider.onProgress = { [weak self] p in Task { @MainActor in self?.message="\(p.accepted) saved · \(p.rejected) rejected\n\(p.guidance)" } }
            provider.start()
            try await Task.sleep(for:.seconds(20))
            _=try await provider.finish()
            try JSONSerialization.data(withJSONObject:mappings,options:[.sortedKeys]).write(to:root.deletingLastPathComponent().appendingPathComponent(root.lastPathComponent+"-framing.json"))
            message="Saved camera validation.\n\(root.lastPathComponent)"
        } catch {
            message=error.localizedDescription
            try? FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
            try? error.localizedDescription.write(to:root.appendingPathComponent("failure.txt"),atomically:true,encoding:.utf8)
        }
    }
}
struct MultiCameraValidationView:View {
    @StateObject var check=MultiCameraValidation()
    var body:some View {
        VStack {
            if let camera=check.camera {MultiCameraPreview(layer:camera.preview) {_,_ in }.frame(maxHeight:.infinity)}
            Text(check.message).padding()
        }.task {await check.start()}
    }
}
#endif
