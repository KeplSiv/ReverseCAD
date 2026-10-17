import SwiftUI

struct DesignView:View {
    @EnvironmentObject var model:AppModel
    let project:RepairProject
    var body:some View {
        VStack(alignment:.leading,spacing:18) {
            Text("Choose a repair hypothesis").font(.title2.bold())
            Text("Missing geometry is a design proposal. Confirm the attachment method and fit-critical values before printing.").font(.footnote).foregroundStyle(.secondary)
            ForEach(FamilySpec.all,id:\.self){family in
                Button {if project.family != family {model.update{$0.family=family;$0.parameters=FamilySpec.defaults(family);$0.attachment=family=="cup_handle" ? "saddle":"screws";$0.repairID=nil}}} label:{
                    HStack(alignment:.top,spacing:12) {Image(systemName:project.family==family ? "checkmark.circle.fill":"circle").font(.title2);VStack(alignment:.leading,spacing:5){Text(FamilySpec.title(family)).font(.headline);Text(description(family)).font(.footnote)};Spacer()}.foregroundStyle(.primary).card()
                }.buttonStyle(.plain).accessibilityIdentifier("family_\(family)")
            }
            VStack(alignment:.leading,spacing:12) {
                Text("Purpose & attachment").font(.headline)
                TextField("Describe the repair",text:binding(\.intent),axis:.vertical).lineLimit(3...6).textFieldStyle(.roundedBorder)
                Picker("Attachment",selection:binding(\.attachment)) {
                    if project.family=="cup_handle" {Text("Approved curved saddle pads").tag("saddle");Text("Surviving stubs (needs evidence)").tag("stubs")}
                    else {Text("Screws / confirmed holes").tag("screws");Text("Contact / adhesive pads").tag("adhesive")}
                }
                if project.family=="cup_handle" {Toggle("I approve curved saddle pads as the attachment method",isOn:Binding(get:{project.saddleApproved ?? false},set:{v in model.update{$0.saddleApproved=v}}));Text("Saddle pads are an explicit alternate repair. Test on an empty room-temperature cup. No adhesive or load rating is implied.").font(.caption).foregroundStyle(.secondary)}
                Picker("Reasoning mode",selection:binding(\.mode)){Text("Manual / template").tag("manual");Text("Offline intent fixture").tag("fixture");Text("Live AI provider").tag("live")}.accessibilityIdentifier("reasoningMode")
                Text(project.mode=="live" ? "Selected images and evidence will be sent by the Mac to its configured model provider. A real API key is required.":project.mode=="fixture" ? "Uses a labeled deterministic typed intent fixture; no live model call is made.":"Your typed parameters drive trusted deterministic CAD. No AI call is made.").font(.caption).foregroundStyle(.secondary)
            }.card()
            VStack(alignment:.leading,spacing:12) {
                Button("Suggest candidates from evidence"){model.suggestCandidates()}.buttonStyle(.bordered).disabled(model.busy || project.scanID==nil || (project.family=="cup_handle" && project.saddleApproved != true)).accessibilityIdentifier("suggestCandidates")
                ForEach(Array(model.candidates.enumerated()),id:\.offset){_,candidate in
                    VStack(alignment:.leading,spacing:8) {
                        Text(candidate["title"] as? String ?? "Candidate").font(.headline)
                        Text(candidate["explanation"] as? String ?? "").font(.footnote)
                        ForEach(candidate["differences"] as? [String] ?? [],id:\.self){Text("• "+$0).font(.caption)}
                        ForEach(candidate["questions"] as? [String] ?? [],id:\.self){Label($0,systemImage:"questionmark.circle").font(.caption)}
                        Button("Apply candidate"){model.applyCandidate(candidate)}.buttonStyle(.bordered)
                    }.card()
                }
                if !model.candidateNotes.isEmpty {DisclosureGroup("Evidence and assumptions"){ForEach(model.candidateNotes,id:\.self){Text($0).font(.caption).padding(.vertical,3)}}}
                ForEach(model.candidateQuestions,id:\.self){Label($0,systemImage:"exclamationmark.triangle").font(.caption)}
            }
            VStack(alignment:.leading,spacing:12) {
                Text("Editable parameters · mm").font(.headline)
                ForEach(project.parameters.keys.sorted(),id:\.self){key in
                    VStack(alignment:.leading,spacing:4) {
                        numeric(FamilySpec.label(key),value:Binding(get:{project.parameters[key] ?? 0},set:{v in model.update{$0.parameters[key]=v}}),id:"param_\(key)")
                        if let d=project.dimensions.last(where:{$0.name==key}) {Text("Manual constraint: \(d.value.formatted()) ±\(d.uncertainty.formatted()) mm. Changing this parameter requires reconfirmation.").font(.caption2).foregroundStyle(.secondary)} else {Text(project.candidateProvenance?[key] ?? "Design inference — not a measured dimension").font(.caption2).foregroundStyle(.secondary)}
                    }
                }
                Text("Bounds and geometric constraints are validated by the service. Existing observations are preserved when a design is rejected.").font(.caption).foregroundStyle(.secondary)
            }.card()
            DisclosureGroup("Printer profile") {
                VStack(spacing:10) {TextField("Material",text:binding(\.material)).textFieldStyle(.roundedBorder);numeric("Nozzle (mm)",value:binding(\.nozzle));numeric("Layer height (mm)",value:binding(\.layerHeight));numeric("Minimum wall (mm)",value:Binding(get:{project.minimumWall ?? 1.2},set:{v in model.update{$0.minimumWall=v}}));ForEach(0..<3){i in numeric("Build \(["X","Y","Z"][i]) (mm)",value:Binding(get:{(project.buildVolume ?? [220,220,250])[i]},set:{v in model.update{p in var volume=p.buildVolume ?? [220,220,250];volume[i]=v;p.buildVolume=volume}}))};Text("Printer error is separate from sensor uncertainty. Print a fit coupon first.").font(.caption)}.padding(.top)
            }.card()
            Toggle("I understand fit is unresolved until measured and test printed",isOn:binding(\.acknowledged)).font(.subheadline).card().accessibilityIdentifier("acknowledgeFit")
            Button {model.generate()} label:{Label(project.revision>0 ? "Generate new revision":"Generate repair",systemImage:"cube.transparent").frame(maxWidth:.infinity)}.buttonStyle(.borderedProminent).controlSize(.large).disabled(model.busy || project.scanID==nil || !project.acknowledged || (project.family=="cup_handle" && project.attachment=="saddle" && project.saddleApproved != true)).accessibilityIdentifier("generateRepair")
            Text("Unknown geometry or unsupported interfaces require more evidence. A valid solid alone does not establish fit or strength.").font(.caption).foregroundStyle(.secondary)
        }
    }
    func description(_ f:String)->String {switch f {case "cup_handle":return "Curved saddle pads on a fitted cup profile; editable spacing and contact gap.";case "bracket":return "Flat or L-shaped bracket with confirmed offsets and mounting holes.";default:return "Arched grip between two selected mounting contacts, with editable standoff and pads."}}
    func binding<T>(_ key:WritableKeyPath<RepairProject,T>)->Binding<T>{Binding(get:{project[keyPath:key]},set:{v in model.update{$0[keyPath:key]=v}})}
}
