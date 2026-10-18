import SwiftUI

enum ObjectFlow: String, Identifiable {
    case scan, repair
    var id: String { rawValue }
    var title: String { self == .scan ? "Scan an object" : "Repair damage" }
    func includes(_ project: RepairProject) -> Bool {
        if let purpose = project.scanPurpose { return purpose == rawValue }
        return self == .scan ? project.repairScope == "standalone_scan" : project.repairScope != "standalone_scan"
    }
}

struct ObjectFlowHome: View {
    @EnvironmentObject private var model: AppModel
    @State private var flow: ObjectFlow?
    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 24) {
                Text("What would you like to do?").font(.largeTitle.bold())
                flowButton(.scan, icon: "viewfinder", detail: "Choose an object, scan it, then preview and export its 3D shape.")
                flowButton(.repair, icon: "wrench.and.screwdriver", detail: "Scan the damaged object, find supported missing regions, then review and export a proposed CAD repair.")
                Text("Capture stays on your phone. Identification uses Jev. 3D processing and repair use your connected Mac.")
                    .font(.footnote).foregroundStyle(.secondary)
                Spacer()
            }.padding(24).navigationTitle("Prelude")
        }
        .fullScreenCover(item: $flow) { selected in StandaloneScanView(flow: selected) }
    }
    private func flowButton(_ selected: ObjectFlow, icon: String, detail: String) -> some View {
        Button {
            guard !model.busy, !model.captureActive else { return }
            model.selectedID = nil; flow = selected
        } label: {
            VStack(alignment: .leading, spacing: 10) {
                Label(selected.title, systemImage: icon).font(.title2.bold())
                Text(detail).font(.body).foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity, alignment: .leading).padding(20)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20))
        }.buttonStyle(.plain).accessibilityIdentifier("flow_" + selected.rawValue)
    }
}
