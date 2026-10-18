import AVFoundation
import SwiftUI

/// Permission is resolved before constructing views that own camera sessions.
@MainActor final class CameraAccess: ObservableObject {
    enum State { case requesting, granted, denied, restricted }
    @Published private(set) var state: State
    private let authorization: () -> AVAuthorizationStatus
    private let request: () async -> Bool
    private var requesting = false

    init(authorization: @escaping () -> AVAuthorizationStatus = { AVCaptureDevice.authorizationStatus(for: .video) },
         request: @escaping () async -> Bool = { await AVCaptureDevice.requestAccess(for: .video) }) {
        self.authorization=authorization;self.request=request
        state=Self.state(for:authorization())
    }
    private static func state(for status:AVAuthorizationStatus)->State {
        switch status {
        case .authorized:return .granted
        case .denied:return .denied
        case .restricted:return .restricted
        case .notDetermined:return .requesting
        @unknown default:return .restricted
        }
    }
    func refresh() async {
        guard !requesting else{return}
        let status=authorization()
        guard status == .notDetermined else {state=Self.state(for:status);return}
        requesting=true;state = .requesting
        let allowed=await request()
        requesting=false
        state=allowed ? .granted : .denied
    }
    static func live()->CameraAccess {
        #if DEBUG
        let args=ProcessInfo.processInfo.arguments
        if args.contains("-cameraAccessGranted") {return CameraAccess(authorization:{.authorized})}
        if args.contains("-cameraAccessDenied") {return CameraAccess(authorization:{.denied})}
        #endif
        return CameraAccess()
    }
}

struct CameraAccessGate<Content:View>:View {
    @StateObject private var access=CameraAccess.live()
    @Environment(\.scenePhase) private var scenePhase
    @ViewBuilder var content:()->Content
    var body:some View {
        Group {
            if access.state == .granted {content()}
            else {
                VStack(spacing:20) {
                    Image(systemName:"camera.fill").font(.system(size:42)).foregroundStyle(RepairStyle.accent)
                    Text("Camera access").font(.title2.bold())
                    if access.state == .requesting {
                        Text("Allow camera access to open the live view.").multilineTextAlignment(.center)
                        ProgressView("Requesting permission…")
                    } else if access.state == .denied {
                        Text("Allow ReverseCAD to use your camera in Settings.").multilineTextAlignment(.center)
                        Button("Open Settings") {
                            if let url=URL(string:UIApplication.openSettingsURLString) {UIApplication.shared.open(url)}
                        }.buttonStyle(RepairButtonStyle()).accessibilityIdentifier("cameraPermissionSettings")
                    } else {
                        Text("Camera access is restricted on this device.").multilineTextAlignment(.center)
                    }
                }.padding(28).frame(maxWidth:.infinity,maxHeight:.infinity)
                    .foregroundStyle(RepairStyle.text).background(RepairStyle.background.ignoresSafeArea())
            }
        }
        .task {await access.refresh()}
        .onChange(of:scenePhase) {_,phase in if phase == .active {Task {await access.refresh()}}}
        .preferredColorScheme(.dark)
    }
}
