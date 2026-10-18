import SwiftUI
import AVKit

/// System capture events support both volume buttons without changing volume
/// or observing private hardware notifications. A release triggers one action.
struct CameraCaptureButton: ViewModifier {
    var enabled: Bool
    var action: () -> Void
    @ViewBuilder func body(content: Content) -> some View {
        if #available(iOS 18.0, *) {
            content.onCameraCaptureEvent(isEnabled: enabled) { event in
                if event.phase == .ended { action() }
            }
        } else if #available(iOS 17.2, *) {
            content.background(VolumeCaptureControl(enabled:enabled,action:action).frame(width:1,height:1))
        } else { content }
    }
}

@available(iOS 17.2, *)
private struct VolumeCaptureControl:UIViewRepresentable {
    let enabled:Bool
    let action:()->Void
    final class CaptureView:UIView {
        var action:(()->Void)?
        var captureInteraction:AVCaptureEventInteraction?
    }
    func makeUIView(context:Context)->CaptureView {
        let view=CaptureView()
        let interaction=AVCaptureEventInteraction {[weak view] event in
            if event.phase == .ended {view?.action?()}
        }
        view.addInteraction(interaction);view.captureInteraction=interaction
        return view
    }
    func updateUIView(_ view:CaptureView,context:Context) {
        view.action=action;view.captureInteraction?.isEnabled=enabled
    }
}

extension View {
    func cameraCaptureButton(enabled: Bool, action: @escaping () -> Void) -> some View {
        modifier(CameraCaptureButton(enabled: enabled, action: action))
    }
}

enum FrontReferencePolicy {
    static let sampleCount = 8
    static let sampleInterval = 0.12
    static let maximumWindow = 1.25
    static func shutterDuration(baseline: Double, minimum: Double) -> Double {
        max(minimum, baseline / 2)
    }
    static func ready(timestamps: [Double], now: Double) -> Bool {
        timestamps.count == sampleCount && timestamps.allSatisfy(\.isFinite)
            && now - timestamps[0] <= maximumWindow
            && now - timestamps[sampleCount - 1] < 0.3
    }
}
