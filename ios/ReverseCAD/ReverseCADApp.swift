import SwiftUI

@main
struct ReverseCADApp: App {
    @StateObject private var model = AppModel()
    var body: some Scene {WindowGroup {ContentView().environmentObject(model).tint(Color(red:0.08,green:0.5,blue:0.57))}}
}
