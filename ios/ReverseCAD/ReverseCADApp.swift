import SwiftUI

@main
struct ReverseCADApp: App {
    @StateObject private var model = AppModel()
    var body: some Scene {WindowGroup {CameraAccessGate {ContentView().environmentObject(model).tint(RepairStyle.accent)}}}
}
