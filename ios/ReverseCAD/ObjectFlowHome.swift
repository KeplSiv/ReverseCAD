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
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("What would you like to do?").font(.largeTitle.bold()).padding(.bottom, 8)
                    flowButton(.scan, icon: "viewfinder", detail: "Choose an object, scan it, then preview and export its 3D shape.")
                    flowButton(.repair, icon: "wrench.and.screwdriver", detail: "Scan a damaged object, then review and export a proposed CAD repair.")
                    Text("Capture stays on your phone. Jev identifies your object. Building the model and finding damage require your connected Mac.")
                        .font(.footnote).foregroundStyle(RepairStyle.secondary).padding(.top, 4)
                }.padding(20).foregroundStyle(RepairStyle.text)
            }
            .background(RepairStyle.background.ignoresSafeArea())
            .navigationTitle("Prelude").navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(RepairStyle.background, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
        }
        .preferredColorScheme(.dark).tint(RepairStyle.accent)
        .fullScreenCover(item: $flow) { selected in StandaloneScanView(flow: selected) }
    }
    private func flowButton(_ selected: ObjectFlow, icon: String, detail: String) -> some View {
        Button {
            guard !model.busy, !model.captureActive else { return }
            model.selectedID = nil; flow = selected
        } label: {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Image(systemName: icon).font(.system(size: 30, weight: .light)).foregroundStyle(RepairStyle.accent)
                    Spacer()
                    Image(systemName: "arrow.up.right").font(.body.weight(.medium)).foregroundStyle(RepairStyle.secondary)
                }
                VStack(alignment: .leading, spacing: 8) {
                    Text(selected.title).font(.title2.bold()).foregroundStyle(RepairStyle.text)
                    Text(detail).font(.subheadline).foregroundStyle(RepairStyle.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }.frame(maxWidth: .infinity, alignment: .leading).padding(22)
                .background(RepairStyle.surface, in: RoundedRectangle(cornerRadius: 22))
                .contentShape(RoundedRectangle(cornerRadius: 22))
        }.buttonStyle(.plain).accessibilityIdentifier("flow_" + selected.rawValue)
            .disabled(model.busy || model.captureActive)
    }
}
