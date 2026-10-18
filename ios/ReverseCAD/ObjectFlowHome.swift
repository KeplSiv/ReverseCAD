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

/// The original main camera remains the entry point; the two workflows share it.
struct ObjectFlowHome: View {
    var body: some View { StandaloneScanView(cameraFirst: true) }
}

struct ObjectFlowPicker: View {
    @Binding var selection: ObjectFlow
    var body: some View {
        HStack(spacing: 4) {
            ForEach([ObjectFlow.scan, .repair]) { flow in
                Button { selection = flow } label: {
                    Text(flow == .scan ? "Scan object" : "Repair damage")
                        .font(.subheadline.weight(.semibold)).frame(maxWidth: .infinity).padding(.vertical, 13)
                        .background(selection == flow ? RepairStyle.selected : Color.clear, in: RoundedRectangle(cornerRadius: 13))
                }.buttonStyle(.plain).accessibilityIdentifier("flow_" + flow.rawValue)
                    .accessibilityAddTraits(selection == flow ? [.isSelected] : [])
            }
        }.padding(4).background(RepairStyle.surface, in: RoundedRectangle(cornerRadius: 17))
    }
}
