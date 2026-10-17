import SwiftUI

struct EvidenceView:View {
    @EnvironmentObject var model:AppModel
    let project:RepairProject
    @State private var selection="contact"
    @State private var viewMode="Surface"
    @State private var dimensionName="span"
    @State private var dimensionValue=80.0
    @State private var dimensionUncertainty=0.1
    @State private var point:[Double]=[0,0,0]
    @State private var normal:[Double]=[0,0,1]
    var body:some View {
        VStack(alignment:.leading,spacing:18) {
            Text("Review the evidence").font(.title2.bold())
            Text("Blue is observed geometry. Tap a visible surface to mark a contact or damage. Orbit with one finger; pinch to zoom.").font(.footnote).foregroundStyle(.secondary)
            Picker("Display",selection:$viewMode){Text("Surface").tag("Surface");Text("Points").tag("Points");Text("Images").tag("Images")}.pickerStyle(.segmented)
            if viewMode=="Images" {SourceImageView(directory:model.scanDirectory)} else {
                GeometryPreview(scan:displayMesh,part:nil,selectionMode:selection,onReject:{model.error=$0}) {p,n in
                    if selection=="fragment" {model.update{$0.fragmentPoints=($0.fragmentPoints ?? [])+[p]}} else if selection=="counterpart" {model.update{$0.counterpartPoints=($0.counterpartPoints ?? [])+[p]}} else if selection=="damage" {model.update{$0.damage.append(p)}} else {model.update{$0.contacts.append(ContactMark(point:p,normal:n))}}
                }.frame(height:280).clipShape(RoundedRectangle(cornerRadius:16)).accessibilityIdentifier("scanPreview")
            }
            Picker("Mark",selection:$selection){Text("Contact").tag("contact");Text("Damage").tag("damage");Text("Counterpart").tag("counterpart");Text("Fragment").tag("fragment")}.pickerStyle(.segmented)
            Text("\(project.contacts.count) contacts · \(project.damage.count) damage · \(project.counterpartPoints?.count ?? 0) counterpart").font(.caption.bold()).accessibilityIdentifier("annotationCount")
            if !model.warnings.isEmpty {VStack(alignment:.leading,spacing:8){ForEach(Array(model.warnings.enumerated()),id:\.offset){_,w in Label(friendlyWarning(w),systemImage:"exclamationmark.triangle")}}.font(.footnote).card()}
            DisclosureGroup("Contact coordinates & corrections") {
                VStack(alignment:.leading,spacing:12) {
                    Text("Coordinates are millimeters in the object frame. Preview picks are approximate; review normals before generating.").font(.caption)
                    vectorFields("Position",values:$point)
                    vectorFields("Normal",values:$normal)
                    Button("Add contact") {let length=sqrt(normal.reduce(0){$0+$1*$1});if length>0 {model.update{$0.contacts.append(ContactMark(point:point.map{$0/1000},normal:normal.map{$0/length},normalSource:"manual",normalConfirmed:true))}}}.accessibilityIdentifier("addContact")
                    ForEach(Array(project.contacts.enumerated()),id:\.element.id){index,c in
                        DisclosureGroup("Contact \(index+1): \(c.point.map{String(format:"%.1f",$0*1000)}.joined(separator:", ")) mm") {
                            VStack(alignment:.leading,spacing:10) {
                                Text("Outward normal: \(c.normal.map{String(format:"%.3f",$0)}.joined(separator:", "))").font(.caption.monospacedDigit())
                                Text(c.normalConfirmed==true ? "User confirmed orientation" : "Estimated from observed surface patch; uncertainty not calibrated").font(.caption2).foregroundStyle(.secondary)
                                vectorFields("Normal",values:Binding(get:{c.normal},set:{v in model.update{p in if let i=p.contacts.firstIndex(where:{$0.id==c.id}) {p.contacts[i].normal=v;p.contacts[i].normalSource="manual";p.contacts[i].normalConfirmed=false}}}))
                                Button("Normalize and confirm orientation") {let length=sqrt(c.normal.reduce(0){$0+$1*$1});if length>0 {model.update{p in if let i=p.contacts.firstIndex(where:{$0.id==c.id}) {p.contacts[i].normal=c.normal.map{$0/length};p.contacts[i].normalConfirmed=true}}}}
                                Button("Remove contact",role:.destructive){model.update{$0.contacts.removeAll{$0.id==c.id}}}
                            }.padding(.top,8)
                        }.font(.caption)
                    }
                    if !project.damage.isEmpty {Button("Clear damage marks"){model.update{$0.damage=[]}}}
                }.padding(.top)
            }.card()
            VStack(alignment:.leading,spacing:12) {
                Text("Measured dimensions").font(.headline)
                if model.measurements.isEmpty {Text("Process the scan to obtain measurements. No unseen hole diameter is inferred.").font(.footnote).foregroundStyle(.secondary)}
                ForEach(Array(model.measurements.enumerated()),id:\.offset){_,m in
                    VStack(alignment:.leading,spacing:4) {Text("\(m["name"] as? String ?? m["id"] as? String ?? "Dimension"): \((m["value"] as? Double ?? 0).formatted(.number.precision(.fractionLength(1)))) mm").font(.subheadline.bold());Text("\(m["source"] ?? "unknown") · \(uncertainty(m))").font(.caption).foregroundStyle(.secondary)}
                }
                ForEach(project.dimensions){d in HStack {VStack(alignment:.leading){Text("\(FamilySpec.label(d.name)): \(d.value.formatted()) mm").font(.subheadline.bold());Text("Manual · ±\(d.uncertainty.formatted()) mm · confirmed").font(.caption).foregroundStyle(.secondary)};Spacer();Button {model.update{$0.dimensions.removeAll{$0.id==d.id}}} label:{Image(systemName:"minus.circle")}.accessibilityLabel("Remove \(d.name)")}}
            }.card()
            VStack(alignment:.leading,spacing:12) {
                Text("Confirm a critical dimension").font(.headline)
                Picker("Dimension",selection:$dimensionName){ForEach(Array(project.parameters.keys.sorted()),id:\.self){Text(FamilySpec.label($0)).tag($0)}}
                numeric("Measured length (mm)",value:$dimensionValue,id:"manualValue")
                numeric("Measurement uncertainty (mm)",value:$dimensionUncertainty,id:"manualUncertainty")
                Button("Save confirmed measurement") {
                    guard project.parameters[dimensionName] != nil,dimensionValue.isFinite,dimensionValue>0,dimensionUncertainty.isFinite,dimensionUncertainty>=0 else{return}
                    model.update {p in p.dimensions.append(ManualDimension(name:dimensionName,value:dimensionValue,uncertainty:dimensionUncertainty));if p.parameters[dimensionName] != nil {p.parameters[dimensionName]=dimensionValue}}
                }.buttonStyle(.bordered).disabled(project.parameters[dimensionName]==nil).accessibilityIdentifier("saveMeasurement")
                Text("Use calipers or a ruler. This value becomes a manual constraint; it is not counted as an automatic scan measurement.").font(.caption).foregroundStyle(.secondary)
            }.card()
            DisclosureGroup("Crop and foreground correction") {
                VStack(alignment:.leading,spacing:10) {
                    Toggle("Apply object-frame crop",isOn:binding(\.cropEnabled))
                    Text("Retain attachment regions. Bounds are in millimeters. Reprocess after saving evidence.").font(.caption)
                    vectorProject("Minimum",key:\.cropMin);vectorProject("Maximum",key:\.cropMax)
                }.padding(.top)
            }.card()
            DisclosureGroup("Scale reference") {
                VStack(alignment:.leading,spacing:10) {
                    numeric("Known length (mm)",value:binding(\.scaleMeasured))
                    numeric("Observed length (mm)",value:binding(\.scaleObserved))
                    numeric("Reference uncertainty (mm)",value:binding(\.scaleUncertainty))
                    Text("The original observations remain unchanged. The correction factor and uncertainty are recorded. Reserve different dimensions to evaluate accuracy.").font(.caption)
                }.padding(.top)
            }.card()
            VStack(alignment:.leading,spacing:10) {
                Text("Available evidence").font(.headline)
                Picker("Evidence",selection:binding(\.evidence)){Text("Missing part").tag("missing_part");Text("Fragment available").tag("fragment");Text("Matching intact part").tag("matching_part")}
                if project.evidence=="fragment" {Text("Select Fragment above and tap the surviving fragment region. \(project.fragmentPoints?.count ?? 0) points selected.").font(.caption)}
                if project.evidence=="matching_part" {Toggle("Confirm counterpart symmetry plane",isOn:binding(\.symmetryConfirmed)).disabled((project.counterpartPoints ?? []).isEmpty);Picker("Object-frame plane normal",selection:binding(\.symmetryAxis)){Text("X").tag("x");Text("Y").tag("y");Text("Z").tag("z")};numeric("Plane offset (mm)",value:Binding(get:{project.symmetryOffset ?? 0},set:{v in model.update{$0.symmetryOffset=v}}));Text("Symmetry is a user-approved assumption, not observed missing geometry.").font(.caption)}
            }.card()
            Button {model.persistAnnotations()} label:{Label("Save evidence",systemImage:"checkmark.seal").frame(maxWidth:.infinity)}.buttonStyle(.borderedProminent).disabled(model.busy).accessibilityIdentifier("saveEvidence")
            Button("Reprocess with crop and scale"){model.uploadAndReconstruct()}.disabled(model.busy || project.scanID==nil)
        }.onAppear{normalizeDimension()}.onChange(of:project.family){_,_ in normalizeDimension()}
    }
    func normalizeDimension() {
        guard project.parameters[dimensionName]==nil else{return}
        dimensionName=project.family=="cup_handle" ? "cup_radius" : project.family=="bracket" ? "hole_spacing" : "span"
        dimensionValue=project.parameters[dimensionName] ?? 0
    }
    func friendlyWarning(_ warning:String)->String {
        if warning.hasPrefix("rgb_insufficient_texture") {return "Not enough image texture or camera separation for multiview refinement. Depth remains the metric source."}
        if warning.hasPrefix("uncertainty") {return "Sensor uncertainty is not calibrated. Independently confirm critical dimensions."}
        return warning.replacingOccurrences(of:"_",with:" ")
    }
    var displayMesh:MeshPreview? {guard var mesh=model.scanMesh else{return nil};if viewMode=="Points" {mesh.triangles=[]};return mesh}
    func uncertainty(_ m:[String:Any])->String {if let v=m["uncertainty_mm"] as? Double{return "uncertainty ±\(v.formatted()) mm"};return "uncertainty not calibrated"}
    func binding<T>(_ key:WritableKeyPath<RepairProject,T>)->Binding<T>{Binding(get:{project[keyPath:key]},set:{v in model.update{$0[keyPath:key]=v}})}
    func vectorProject(_ label:String,key:WritableKeyPath<RepairProject,[Double]>)->some View {vectorFields(label,values:binding(key))}
    func vectorFields(_ label:String,values:Binding<[Double]>)->some View {HStack {Text(label).font(.caption).frame(width:62,alignment:.leading);ForEach(0..<3){i in TextField(["X","Y","Z"][i],value:Binding(get:{values.wrappedValue[i]},set:{values.wrappedValue[i]=$0}),format:.number).keyboardType(.numbersAndPunctuation).textFieldStyle(.roundedBorder).accessibilityLabel("\(label) \(["X","Y","Z"][i])")}}}
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
