import SwiftUI

struct DesignView: View {
    @EnvironmentObject var model: AppModel
    let project: RepairProject
    @State private var manualTemplate = false

    var enoughContacts: Bool {
        project.family == "bracket" ? (1...2).contains(project.contacts.count) : project.contacts.count == 2
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("3. Propose the missing piece").font(.title2.bold())
            Text("Choose the kind of replacement. The app uses the intact surfaces you marked to propose editable CAD. The missing original shape is not directly observed.")
                .font(.subheadline).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 12) {
                Picker("Replacement type", selection: Binding(
                    get: { project.family },
                    set: { family in
                        model.update {
                            $0.family = family
                            $0.parameters = FamilySpec.defaults(family)
                            $0.attachment = family == "cup_handle" ? "saddle" : "screws"
                            $0.repairID = nil
                            $0.candidateID = nil
                        }
                    }
                )) {
                    ForEach(FamilySpec.all, id: \.self) { family in Text(FamilySpec.title(family)).tag(family) }
                }
                .accessibilityIdentifier("repairType")
                Text(description(project.family)).font(.footnote).foregroundStyle(.secondary)
                Picker("How it attaches", selection: binding(\.attachment)) {
                    if project.family == "cup_handle" {
                        Text("Curved saddle pads").tag("saddle")
                        Text("Surviving stubs").tag("stubs")
                    } else {
                        Text("Screws / confirmed holes").tag("screws")
                        Text("Contact / adhesive pads").tag("adhesive")
                    }
                }
                if project.family == "cup_handle" {
                    Toggle("I approve curved saddle pads", isOn: Binding(
                        get: { project.saddleApproved ?? false },
                        set: { value in model.update { $0.saddleApproved = value } }
                    ))
                    Text("The app cannot infer a broken cup stub or adhesive strength from this scan.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }.card()
            if !enoughContacts {
                Label(project.family == "bracket" ? "Mark one or two intact mating surfaces above." : "Mark exactly two intact attachment surfaces above.", systemImage: "hand.tap")
                    .font(.footnote).foregroundStyle(.orange)
            }
            Button { model.suggestCandidates() } label: {
                Label("Suggest repair shapes", systemImage: "sparkles.rectangle.stack")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(model.busy || !enoughContacts || (project.family == "cup_handle" && project.saddleApproved != true))
            .accessibilityIdentifier("suggestCandidates")
            if !model.candidates.isEmpty {
                Text("Choose a shape to preview").font(.headline)
                ForEach(Array(model.candidates.enumerated()), id: \.offset) { _, candidate in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(candidate["title"] as? String ?? "Repair shape").font(.headline)
                        Text(candidate["explanation"] as? String ?? "").font(.footnote)
                        ForEach(candidate["differences"] as? [String] ?? [], id: \.self) { difference in
                            Text("• " + difference).font(.caption)
                        }
                        Button(project.candidateID == candidate["id"] as? String ? "Selected" : "Use this shape") {
                            model.applyCandidate(candidate)
                        }
                        .buttonStyle(.bordered)
                        .disabled(project.candidateID == candidate["id"] as? String)
                        .accessibilityIdentifier("applyCandidate")
                    }.card()
                }
            } else if project.candidateID != nil {
                Label("Repair shape selected", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.teal)
            }
            ForEach(model.candidateQuestions, id: \.self) { question in
                Label(question, systemImage: "questionmark.circle")
                    .font(.footnote).foregroundStyle(.orange)
            }
            if !model.candidateNotes.isEmpty {
                DisclosureGroup("How this shape was inferred") {
                    ForEach(model.candidateNotes, id: \.self) { note in
                        Text(note).font(.footnote).padding(.vertical, 3)
                    }
                }.card()
            }
            DisclosureGroup("Edit dimensions and advanced options") {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Editable dimensions · mm").font(.headline)
                    ForEach(project.parameters.keys.sorted(), id: \.self) { key in
                        VStack(alignment: .leading, spacing: 3) {
                            numeric(FamilySpec.label(key), value: Binding(
                                get: { project.parameters[key] ?? 0 },
                                set: { value in model.update { $0.parameters[key] = value } }
                            ), id: "param_\(key)")
                            Text(project.candidateProvenance?[key] ?? "Design proposal — not a measured dimension")
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                    TextField("Describe the repair", text: binding(\.intent), axis: .vertical)
                        .lineLimit(2...4).textFieldStyle(.roundedBorder)
                    Picker("Reasoning mode", selection: binding(\.mode)) {
                        Text("Manual / template").tag("manual")
                        Text("Offline intent fixture").tag("fixture")
                        Text("Live AI provider").tag("live")
                    }.accessibilityIdentifier("reasoningMode")
                    Text(project.mode == "live" ? "The paired Mac sends selected images and evidence to its configured model provider. A real API key is required." : "This mode does not call an AI model.")
                        .font(.caption).foregroundStyle(.secondary)
                    Toggle("Use manual template without a suggested shape", isOn: $manualTemplate)
                    TextField("Material", text: binding(\.material)).textFieldStyle(.roundedBorder)
                    numeric("Nozzle (mm)", value: binding(\.nozzle))
                    numeric("Layer height (mm)", value: binding(\.layerHeight))
                    numeric("Minimum wall (mm)", value: Binding(
                        get: { project.minimumWall ?? 1.2 },
                        set: { value in model.update { $0.minimumWall = value } }
                    ))
                }.padding(.top, 8)
            }.card()
            if project.candidateID != nil || manualTemplate {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Before making CAD").font(.headline)
                    Text("Check mounting dimensions with calipers. A valid digital solid does not prove the part will fit or carry load.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Toggle("I understand physical fit is untested", isOn: binding(\.acknowledged))
                        .accessibilityIdentifier("acknowledgeFit")
                    Button { model.generate() } label: {
                        Label(project.revision > 0 ? "Generate updated CAD" : "Generate proposed CAD", systemImage: "cube.transparent")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.busy || !project.acknowledged || (project.family == "cup_handle" && project.attachment == "saddle" && project.saddleApproved != true))
                    .accessibilityIdentifier("generateRepair")
                }.card()
            }

        }
    }

    func description(_ family: String) -> String {
        switch family {
        case "cup_handle": return "A replacement grip with curved pads on an observed cup surface."
        case "bracket": return "A flat or right-angle bracket joining selected mating surfaces."
        default: return "An arched grip between two selected mounting surfaces."
        }
    }
    func binding<T>(_ key: WritableKeyPath<RepairProject, T>) -> Binding<T> {
        Binding(get: { project[keyPath: key] }, set: { value in model.update { $0[keyPath: key] = value } })
    }
}
