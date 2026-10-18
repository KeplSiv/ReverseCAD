import SwiftUI
import AVFoundation

struct MultiCameraPreview: UIViewRepresentable {
    let layer: AVCaptureVideoPreviewLayer
    var onLayout: (CGSize, UIInterfaceOrientation) -> Void
    func makeUIView(context:Context)->CameraView {
        let view=CameraView();view.captureLayer=layer;view.onLayout=onLayout
        view.layer.addSublayer(layer)
        view.accessibilityLabel="Live camera. Adjust the rectangle around one object."
        return view
    }
    func updateUIView(_ view:CameraView,context:Context) {
        view.onLayout=onLayout
        if view.captureLayer !== layer {view.captureLayer?.removeFromSuperlayer();view.captureLayer=layer;view.layer.addSublayer(layer)}
        view.setNeedsLayout()
    }
    final class CameraView:UIView {
        var captureLayer:AVCaptureVideoPreviewLayer?
        var onLayout:((CGSize,UIInterfaceOrientation)->Void)?
        override func layoutSubviews() {
            super.layoutSubviews()
            let orientation=window?.windowScene?.interfaceOrientation ?? .portrait
            let angle:CGFloat=orientation == .landscapeLeft ? 0 : orientation == .landscapeRight ? 180 : orientation == .portraitUpsideDown ? 270 : 90
            CATransaction.begin();CATransaction.setDisableActions(true)
            captureLayer?.frame=bounds
            if let connection=captureLayer?.connection,connection.isVideoRotationAngleSupported(angle) {connection.videoRotationAngle=angle}
            CATransaction.commit()
            if bounds.width>0,bounds.height>0 {DispatchQueue.main.async {[weak self] in self?.onLayout?(self?.bounds.size ?? .zero,orientation)}}
        }
    }
}
