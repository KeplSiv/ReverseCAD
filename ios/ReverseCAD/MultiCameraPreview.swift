import SwiftUI
import AVFoundation

struct MultiCameraPreview: UIViewRepresentable {
    let layer: AVCaptureVideoPreviewLayer
    var onLayout: (CGSize, UIInterfaceOrientation) -> Void
    func makeUIView(context:Context)->CameraView {
        let view=CameraView();view.attach(layer);view.onLayout=onLayout
        view.accessibilityLabel="Live camera. Adjust the rectangle around one object."
        return view
    }
    func updateUIView(_ view:CameraView,context:Context) {
        view.onLayout=onLayout
        if view.captureLayer !== layer {view.attach(layer)}
        view.setNeedsLayout()
    }
    static func dismantleUIView(_ view:CameraView,coordinator:()) {view.detach()}
    final class CameraView:UIView {
        var captureLayer:AVCaptureVideoPreviewLayer?
        var onLayout:((CGSize,UIInterfaceOrientation)->Void)?
        private var observation:NSKeyValueObservation?
        private let openingCover=UIView()
        private let opening=UIStackView()
        override init(frame:CGRect) {
            super.init(frame:frame)
            let spinner=UIActivityIndicatorView(style:.medium);spinner.startAnimating()
            let title=UILabel();title.text="Opening rear camera…";title.textColor = .white;title.textAlignment = .center
            opening.axis = .vertical;opening.spacing=12;opening.alignment = .center;opening.distribution = .equalCentering
            opening.addArrangedSubview(spinner);opening.addArrangedSubview(title)
            backgroundColor=UIColor(RepairStyle.background)
            openingCover.backgroundColor=backgroundColor
            openingCover.addSubview(opening);addSubview(openingCover)
        }
        required init?(coder:NSCoder) {fatalError("init(coder:) has not been implemented")}
        func attach(_ preview:AVCaptureVideoPreviewLayer) {
            detach();captureLayer=preview;layer.insertSublayer(preview,at:0)
            openingCover.isHidden=preview.isPreviewing
            observation=preview.observe(\.isPreviewing,options:[.initial,.new]) { [weak self] preview,_ in
                let displaying=preview.isPreviewing
                DispatchQueue.main.async {
                    guard let self,self.captureLayer === preview else{return}
                    self.openingCover.isHidden=displaying
                    #if DEBUG
                    if ProcessInfo.processInfo.arguments.contains(where:{$0 == "-rearPreviewCheck" || $0 == "-multiCameraCheck"}) {
                        try? cameraJSONWrite(["preview_displaying":displaying,"mode":"native AVCaptureVideoPreviewLayer","interpolation":false,"uptime_s":ProcessInfo.processInfo.systemUptime],FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("native-rear-preview.json"))
                    }
                    #endif
                }
            }
        }
        func detach() {observation?.invalidate();observation=nil;captureLayer?.removeFromSuperlayer();captureLayer=nil}
        override func layoutSubviews() {
            super.layoutSubviews()
            let orientation=window?.windowScene?.interfaceOrientation ?? .portrait
            let angle:CGFloat=orientation == .landscapeLeft ? 0 : orientation == .landscapeRight ? 180 : orientation == .portraitUpsideDown ? 270 : 90
            CATransaction.begin();CATransaction.setDisableActions(true)
            captureLayer?.frame=bounds
            if let connection=captureLayer?.connection,connection.isVideoRotationAngleSupported(angle) {connection.videoRotationAngle=angle}
            CATransaction.commit()
            openingCover.frame=bounds
            opening.frame=CGRect(x:0,y:max(0,bounds.midY-32),width:bounds.width,height:64)
            if bounds.width>0,bounds.height>0 {DispatchQueue.main.async {[weak self] in self?.onLayout?(self?.bounds.size ?? .zero,orientation)}}
        }
    }
}
