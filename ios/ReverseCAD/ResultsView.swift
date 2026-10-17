import SwiftUI

struct ResultsView:View {
    @EnvironmentObject var model:AppModel
    let project:RepairProject
    @State private var showScan=true
    @State private var showPart=true
    @State private var feedbackSaved=false
    var body:some View {
        VStack(alignment:.leading,spacing:18) {
            Text(project.revision>0 ? "4. Review your repair":"4. Compare and validate").font(.title2.bold()).accessibilityIdentifier("revisionTitle")
            Text("Repair revision \(project.revision) · proposed geometry").font(.subheadline).foregroundStyle(.secondary)
            GeometryPreview(scan:model.scanMesh,part:model.partMesh,showScan:showScan,showPart:showPart,selectionMode:"none",contactPoints:project.contacts.map(\.point),damagePoints:project.damage).frame(height:300).clipShape(RoundedRectangle(cornerRadius:16)).accessibilityIdentifier("comparisonPreview")
            HStack {Toggle("Observed scan",isOn:$showScan).tint(.blue);Toggle("Proposed part",isOn:$showPart).tint(.orange)}.font(.caption)
            HStack {Label("Observed",systemImage:"circle.fill").foregroundStyle(.blue);Label("Inferred repair",systemImage:"circle.fill").foregroundStyle(.orange)}.font(.caption)
            VStack(alignment:.leading,spacing:12) {
                Label(model.validForExport ? "CAD checks passed":"Needs measurements or CAD validation",systemImage:model.validForExport ? "checkmark.seal.fill":"exclamationmark.triangle").font(.headline).accessibilityIdentifier("validationState")
                Text("Live sensing: not validated by this software result. Physical fit: \(project.physicalFit.lowercased()).").font(.footnote).foregroundStyle(.secondary)
                if !model.validation.isEmpty {
                    ForEach(summaryRows,id:\.0){name,value in HStack(alignment:.top){Text(FamilySpec.label(name)).font(.caption.bold());Spacer();Text(value).font(.caption).multilineTextAlignment(.trailing)}}
                    DisclosureGroup("Full validation report") {Text(prettyValidation).font(.system(.caption,design:.monospaced)).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading)}
                }
            }.card()
            if !model.artifacts.isEmpty {
                Button {model.exportArtifacts()} label:{Label("Export CAD & fit coupons",systemImage:"square.and.arrow.up").frame(maxWidth:.infinity)}.buttonStyle(.borderedProminent).controlSize(.large).disabled(!model.validForExport).accessibilityIdentifier("exportCAD")
                DisclosureGroup("CAD files and validation details") {
                    VStack(alignment:.leading,spacing:10) {
                        ForEach(model.artifacts){file in HStack {Image(systemName:file.name.hasSuffix("step") ? "cube":"doc");Text(file.name).font(.caption.monospaced());Spacer();Text(ByteCountFormatter.string(fromByteCount:Int64(file.size),countStyle:.file)).font(.caption).foregroundStyle(.secondary)}}
                        Text("Hashes checked after download. STEP/STL use millimeters; parameters and source preserve editability.").font(.caption).foregroundStyle(.secondary)
                    }.padding(.top,8)
                }.card()
            }
            DisclosureGroup("Record a print and fit test") {VStack(alignment:.leading,spacing:12) {
                Text("Record a real print trial · revision \(project.revision)").font(.headline)
                Text("Leave this untested until an actual coupon or part is printed and compared with independent measurements.").font(.caption).foregroundStyle(.secondary)
                Picker("Physical fit",selection:binding(\.physicalFit)){Text("Not tested").tag("Not tested");Text("Coupon passed").tag("Coupon passed");Text("Part fits").tag("Part fits");Text("Adjustment needed").tag("Adjustment needed")}
                TextField("Printer / slicer / settings",text:binding(\.printer),axis:.vertical).textFieldStyle(.roundedBorder)
                Stepper("Print iterations: \(project.printIterations)",value:binding(\.printIterations),in:0...100)
                TextField("Measured printed dimensions, contact gaps, finishing, and trial notes",text:binding(\.feedback),axis:.vertical).lineLimit(4...10).textFieldStyle(.roundedBorder).accessibilityIdentifier("fitFeedback")
                Button("Save physical-test notes"){model.save();feedbackSaved=true}.accessibilityIdentifier("saveFeedback")
                if let history=project.trialHistory,!history.isEmpty {DisclosureGroup("Previous revision trials"){ForEach(Array(history.enumerated()),id:\.offset){_,trial in Text("Revision \(trial.revision): \(trial.fit). \(trial.feedback)").font(.caption)}}}
                if feedbackSaved {Label("Saved locally",systemImage:"checkmark.circle").font(.caption)}
            }.padding(.top,8)}.card()
        }
    }
    var prettyValidation:String {guard let d=try? JSONSerialization.data(withJSONObject:model.validation,options:[.prettyPrinted,.sortedKeys]),let s=String(data:d,encoding:.utf8) else{return ""};return s}
    var summaryRows:[(String,String)] {model.validation.keys.sorted().filter{["valid","status","solid_count","watertight","volume_mm3","minimum_thickness_mm","warnings","physical_fit"].contains($0)}.map{($0,String(describing:model.validation[$0] ?? ""))}}
    func binding<T>(_ key:WritableKeyPath<RepairProject,T>)->Binding<T>{Binding(get:{project[keyPath:key]},set:{v in model.update{$0[keyPath:key]=v}})}
}
