import SwiftUI
import AVFoundation
import MetalKit

struct MultiCameraPreview: UIViewRepresentable {
    let layer: AVCaptureVideoPreviewLayer
    var source: SmoothCameraRenderer.Source? = nil
    var onLayout: (CGSize, UIInterfaceOrientation) -> Void
    func makeUIView(context:Context)->CameraView {
        let view=CameraView();view.captureLayer=layer;view.onLayout=onLayout
        view.layer.addSublayer(layer)
        view.installSmoothPreview(source:source)
        view.accessibilityLabel="Live camera. Adjust the rectangle around one object."
        return view
    }
    func updateUIView(_ view:CameraView,context:Context) {
        view.onLayout=onLayout
        view.renderer?.source=source
        if view.captureLayer !== layer {view.captureLayer?.removeFromSuperlayer();view.captureLayer=layer;view.layer.addSublayer(layer)}
        view.setNeedsLayout()
    }
    final class CameraView:UIView {
        var captureLayer:AVCaptureVideoPreviewLayer?
        var onLayout:((CGSize,UIInterfaceOrientation)->Void)?
        private var smoothView:MTKView?
        var renderer:SmoothCameraRenderer?
        func installSmoothPreview(source:SmoothCameraRenderer.Source?) {
            guard source != nil else{return}
            let view=MTKView(frame:bounds)
            guard let renderer=SmoothCameraRenderer(view:view) else{return}
            renderer.source=source;self.renderer=renderer;smoothView=view
            view.isUserInteractionEnabled=false;addSubview(view)
        }
        override func layoutSubviews() {
            super.layoutSubviews()
            let orientation=window?.windowScene?.interfaceOrientation ?? .portrait
            let angle:CGFloat=orientation == .landscapeLeft ? 0 : orientation == .landscapeRight ? 180 : orientation == .portraitUpsideDown ? 270 : 90
            CATransaction.begin();CATransaction.setDisableActions(true)
            captureLayer?.frame=bounds
            if let connection=captureLayer?.connection,connection.isVideoRotationAngleSupported(angle) {connection.videoRotationAngle=angle}
            CATransaction.commit()
            smoothView?.frame=bounds
            smoothView?.drawableSize=orientation.isLandscape ? CGSize(width:1920,height:1080) : CGSize(width:1080,height:1920)
            renderer?.orientation=orientation
            if bounds.width>0,bounds.height>0 {DispatchQueue.main.async {[weak self] in self?.onLayout?(self?.bounds.size ?? .zero,orientation)}}
        }
    }
}
