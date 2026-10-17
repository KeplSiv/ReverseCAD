import SwiftUI

struct EvidenceView: View {
    @EnvironmentObject var model: AppModel
    let project: RepairProject
    @State private var selection = "damage"
    @State private var dimensionName = "span"
    @State private var dimensionValue = 80.0
    @State private var dimensionUncertainty = 0.1
    @State private var point: [Double] = [0, 0, 0]
    @State private var normal: [Double] = [0, 0, 1]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("2. Show what is broken").font(.title2.bold())
            Text("Tap the broken edge or missing area, then tap the intact surfaces where a replacement should attach.")
                .font(.subheadline).foregroundStyle(.secondary)
            GeometryPreview(
                scan: model.scanMesh,
                part: nil,
                selectionMode: selection,
                contactPoints: project.contacts.map(\.point),
                damagePoints: project.damage,
                onReject: { model.error = $0 }
            ) { point, normal in
                switch selection {
                case "damage": model.update { $0.damage.append(point) }
                case "fragment": model.update { $0.fragmentPoints = ($0.fragmentPoints ?? []) + [point] }
                case "counterpart": model.update { $0.counterpartPoints = ($0.counterpartPoints ?? []) + [point] }
                default: model.update { $0.contacts.append(ContactMark(point: point, normal: normal)) }
                }
            }
            .frame(height: 280)
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .accessibilityIdentifier("scanPreview")
            HStack {
                markButton("Mark break", icon: "bolt.fill", mode: "damage", color: .pink)
                markButton("Mark attachment", icon: "circle.dotted.circle.fill", mode: "contact", color: .yellow)
            }
            Text(selection == "damage" ? "Pink marks show where material is missing. This helps describe the damage; the shape is inferred from surviving attachment surfaces." : "Yellow marks show intact attachment surfaces. Select two for a handle, or one or two for a bracket.")
                .font(.footnote).foregroundStyle(.secondary)
            HStack {
                Text("\(project.damage.count) break marks · \(project.contacts.count) attachment marks")
                    .font(.caption.bold()).accessibilityIdentifier("annotationCount")
                Spacer()
                if selection == "damage" && !project.damage.isEmpty {
                    Button("Undo") { model.update { $0.damage.removeLast() } }
                } else if selection == "contact" && !project.contacts.isEmpty {
                    Button("Undo") { model.update { $0.contacts.removeLast() } }
                }
            }
            if !model.warnings.isEmpty {
                ForEach(Array(model.warnings.enumerated()), id: \.offset) { _, warning in
                    Label(friendlyWarning(warning), systemImage: "exclamationmark.triangle")
                        .font(.footnote).foregroundStyle(.orange)
                }
            }
            DisclosureGroup("Add a measured dimension") {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Use calipers for fit-critical dimensions. A scan click does not confirm an unseen hole or mating surface.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Picker("Dimension", selection: $dimensionName) {
                        ForEach(project.parameters.keys.sorted(), id: \.self) { key in Text(FamilySpec.label(key)).tag(key) }
                    }
                    numeric("Measured length (mm)", value: $dimensionValue, id: "manualValue")
                    numeric("Uncertainty (mm)", value: $dimensionUncertainty, id: "manualUncertainty")
                    Button("Save measurement") {
                        guard project.parameters[dimensionName] != nil,
                              dimensionValue.isFinite, dimensionValue > 0,
                              dimensionUncertainty.isFinite, dimensionUncertainty >= 0 else { return }
                        model.update { project in
                            project.dimensions.append(ManualDimension(name: dimensionName, value: dimensionValue, uncertainty: dimensionUncertainty))
                            project.parameters[dimensionName] = dimensionValue
                        }
                    }
                    .accessibilityIdentifier("saveMeasurement")
                    ForEach(project.dimensions) { dimension in
                        HStack {
                            Text("\(FamilySpec.label(dimension.name)): \(dimension.value.formatted()) mm")
                                .font(.caption)
                            Spacer()
                            Button { model.update { $0.dimensions.removeAll { $0.id == dimension.id } } } label: {
                                Image(systemName: "minus.circle")
                            }.accessibilityLabel("Remove \(dimension.name)")
                        }
                    }
                }.padding(.top, 8)
            }.card()
            DisclosureGroup("More scan evidence") {
                VStack(alignment: .leading, spacing: 12) {
                    SourceImageView(directory: model.scanDirectory)
                    Text("Observed scan measurements").font(.headline)
                    if model.measurements.isEmpty { Text("No scan measurements yet.").font(.caption) }
                    ForEach(Array(model.measurements.enumerated()), id: \.offset) { _, measurement in
                        Text("\(measurement["name"] as? String ?? "Dimension"): \((measurement["value"] as? Double ?? 0).formatted()) mm")
                            .font(.caption)
                    }
                    Picker("Other evidence", selection: binding(\.evidence)) {
                        Text("Missing part").tag("missing_part")
                        Text("Fragment available").tag("fragment")
                        Text("Matching intact part").tag("matching_part")
                    }
                    if project.evidence == "fragment" || project.evidence == "matching_part" {
                        Button(project.evidence == "fragment" ? "Mark fragment" : "Mark matching part") {
                            selection = project.evidence == "fragment" ? "fragment" : "counterpart"
                        }
                    }
                    if project.evidence == "matching_part" {
                        Toggle("I confirm the matching part is symmetric", isOn: binding(\.symmetryConfirmed))
                            .disabled((project.counterpartPoints ?? []).isEmpty)
                        Picker("Symmetry axis", selection: binding(\.symmetryAxis)) {
                            Text("X").tag("x"); Text("Y").tag("y"); Text("Z").tag("z")
                        }
                        numeric("Plane offset (mm)", value: Binding(
                            get: { project.symmetryOffset ?? 0 },
                            set: { value in model.update { $0.symmetryOffset = value } }
                        ))
                    }
                    Button("Save evidence") { model.persistAnnotations() }
                        .accessibilityIdentifier("saveEvidence")
                }.padding(.top, 8)
            }.card()
            DisclosureGroup("Scan corrections") {
                VStack(alignment: .leading, spacing: 10) {
                    Toggle("Crop background", isOn: binding(\.cropEnabled))
                    vectorProject("Minimum", key: \.cropMin)
                    vectorProject("Maximum", key: \.cropMax)
                    numeric("Known length (mm)", value: binding(\.scaleMeasured))
                    numeric("Observed length (mm)", value: binding(\.scaleObserved))
                    numeric("Reference uncertainty (mm)", value: binding(\.scaleUncertainty))
                    Button("Reprocess scan") { model.uploadAndReconstruct() }
                }.padding(.top, 8)
            }.card()
            DisclosureGroup("Contact coordinates") {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Coordinates are millimeters. Surface normals from a tap are approximate.").font(.caption)
                    vectorFields("Position", values: $point)
                    vectorFields("Normal", values: $normal)
                    Button("Add contact") {
                        let length = sqrt(normal.reduce(0) { $0 + $1 * $1 })
                        if length > 0 {
                            model.update { $0.contacts.append(ContactMark(point: point.map { $0 / 1000 }, normal: normal.map { $0 / length }, normalSource: "manual", normalConfirmed: true)) }
                        }
                    }.accessibilityIdentifier("addContact")
                    ForEach(Array(project.contacts.enumerated()), id: \.element.id) { index, contact in
                        HStack {
                            Text("Contact \(index + 1): \(contact.point.map { String(format: "%.1f", $0 * 1000) }.joined(separator: ", ")) mm")
                                .font(.caption)
                            Spacer()
                            Button { model.update { $0.contacts.removeAll { $0.id == contact.id } } } label: {
                                Image(systemName: "minus.circle")
                            }.accessibilityLabel("Remove contact \(index + 1)")
                        }
                    }
                }.padding(.top, 8)
            }.card()
        }
        .onAppear { normalizeDimension() }
        .onChange(of: project.family) { _, _ in normalizeDimension() }
    }

    func markButton(_ title: String, icon: String, mode: String, color: Color) -> some View {
        Button { selection = mode } label: {
            Label(title, systemImage: icon).frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .tint(selection == mode ? color : .gray)
        .accessibilityIdentifier("mark_\(mode)")
    }
    func normalizeDimension() {
        dimensionName = project.family == "cup_handle" ? "cup_radius" : project.family == "bracket" ? "hole_spacing" : "span"
        dimensionValue = project.parameters[dimensionName] ?? 0
    }
    func friendlyWarning(_ warning: String) -> String {
        if warning.hasPrefix("rgb_insufficient_texture") { return "More image texture or camera separation is needed. Depth remains the metric source." }
        if warning.hasPrefix("uncertainty") { return "Sensor uncertainty is not calibrated. Confirm critical dimensions with calipers." }
        return warning.replacingOccurrences(of: "_", with: " ")
    }
    func binding<T>(_ key: WritableKeyPath<RepairProject, T>) -> Binding<T> {
        Binding(get: { project[keyPath: key] }, set: { value in model.update { $0[keyPath: key] = value } })
    }
    func vectorProject(_ label: String, key: WritableKeyPath<RepairProject, [Double]>) -> some View {
        vectorFields(label, values: binding(key))
    }
    func vectorFields(_ label: String, values: Binding<[Double]>) -> some View {
        HStack {
            Text(label).font(.caption).frame(width: 62, alignment: .leading)
            ForEach(0..<3) { index in
                TextField(["X", "Y", "Z"][index], value: Binding(
                    get: { values.wrappedValue[index] },
                    set: { values.wrappedValue[index] = $0 }
                ), format: .number)
                .keyboardType(.numbersAndPunctuation)
                .textFieldStyle(.roundedBorder)
                .accessibilityLabel("\(label) \(["X", "Y", "Z"][index])")
            }
        }
    }
}

@ViewBuilder func numeric(_ title:String,value:Binding<Double>,id:String="") -> some View {
    HStack {Text(title).font(.subheadline);Spacer();TextField(title,value:value,format:.number).multilineTextAlignment(.trailing).keyboardType(.numbersAndPunctuation).frame(minWidth:70,maxWidth:120).textFieldStyle(.roundedBorder).accessibilityIdentifier(id).accessibilityLabel(title)}
}
struct SourceImageView:View {
    let directory:URL?
    @State private var selected=0
    var files:[URL] {guard let directory else{return []};return ((try? FileManager.default.contentsOfDirectory(at:directory.appendingPathComponent("rgb"),includingPropertiesForKeys:nil)) ?? []).sorted{$0.path<$1.path}}
    var frameMetadata:String {
        guard let directory,!files.isEmpty,let content=try? String(contentsOf:directory.appendingPathComponent("frames.jsonl"),encoding:.utf8) else{return ""}
        let file=files[min(selected,files.count-1)].lastPathComponent
        for line in content.split(separator:"\n") {
            if let data=String(line).data(using:.utf8),let frame=try? JSONSerialization.jsonObject(with:data) as? [String:Any],(frame["rgb_path"] as? String)?.hasSuffix(file)==true {
                return "Raw \(frame["rgb_width"] ?? "?") × \(frame["rgb_height"] ?? "?") px · orientation \(frame["orientation"] ?? "unknown") · t=\(frame["timestamp_s"] ?? "?") s · \(frame["tracking_state"] ?? "unknown")"
            }
        }
        return "Calibrated source image; raw pixel orientation preserved."
    }
    var body:some View {VStack {if files.isEmpty {ContentUnavailableView("No source image",systemImage:"photo")} else {if let image=UIImage(contentsOfFile:files[min(selected,files.count-1)].path){Image(uiImage:image).resizable().scaledToFit().frame(maxHeight:250)};Stepper("Calibrated keyframe \(selected+1) / \(files.count)",value:$selected,in:0...max(0,files.count-1)).font(.caption);Text(frameMetadata).font(.caption2).foregroundStyle(.secondary)}}.frame(minHeight:220).card()}
}
