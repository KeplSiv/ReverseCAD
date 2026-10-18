import SwiftUI

struct ComparisonReport: Codable {
    let schema_version: Int
    let scan_id: String
    let variants: [ComparisonVariant]
    let suggested_variant_id: String
    let conclusion: String
}
struct ComparisonVariant: Codable, Identifiable {
    let id: String
    let title: String
    let method: String
    let status: String
    let message: String
    let scan_preview: String?
    let part_preview: String?
    let print_files: [String]
    let printable: Bool
    let seconds: Double?
    let metrics: Metrics
    struct Metrics: Codable {
        let triangles: Int?
        let surface_triangles: Int?
        let cross_pair_supported_pixels: Int?
        let native_depth_agreement_mm: Double?
        let scale_dispersion: Double?
        let device: String?
        let load_seconds: Double?
    }
    var statusText: String {
        switch status {
        case "proposal_needs_review": return "Exterior prototype · review required"
        case "surface_only": return "Surface recovered · no verified replacement"
        case "unavailable": return "Unavailable on this Mac"
        case "failed": return "Method failed · other results preserved"
        default: return "Insufficient evidence"
        }
    }
}

struct ComparisonPanel: View {
    @EnvironmentObject var model: AppModel
    @State private var showScan = false
    @State private var showRepair = true
    var body: some View {
        VStack(spacing: 12) {
            Text("One scan · multiple methods").font(.headline)
            Picker("Method", selection: Binding(get: { model.selectedComparisonID ?? "" }, set: { model.selectComparison($0) })) {
                Text("Choose a method").tag("")
                ForEach(model.comparison?.variants ?? []) { variant in Text(variant.title).tag(variant.id) }
            }.pickerStyle(.menu).accessibilityIdentifier("comparisonMethod")
            if let variant = model.selectedComparison {
                if model.comparisonScan != nil || model.comparisonPart != nil {
                    GeometryPreview(scan: (showScan || model.comparisonPart == nil) ? model.comparisonScan : nil, part: showRepair ? model.comparisonPart : nil, selectionMode: "none")
                        .frame(minHeight: 260, maxHeight: .infinity).clipShape(RoundedRectangle(cornerRadius: 20))
                    HStack {
                        Toggle("Show on scan", isOn: $showScan).tint(.blue).disabled(model.comparisonPart == nil)
                        Toggle("Proposal", isOn: $showRepair).tint(.orange).disabled(model.comparisonPart == nil)
                    }.font(.caption)
                } else {
                    Spacer(minLength: 10)
                    Image(systemName: variant.status == "unavailable" ? "desktopcomputer.trianglebadge.exclamationmark" : "viewfinder.trianglebadge.exclamationmark")
                        .font(.system(size: 50)).foregroundStyle(.orange)
                    Spacer(minLength: 10)
                }
                Text(variant.statusText).font(.headline).multilineTextAlignment(.center)
                Text(variant.message).font(.subheadline).multilineTextAlignment(.center)
                DisclosureGroup("Method & checks") {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(variant.method)
                            if let seconds = variant.seconds, seconds > 0 { Text(String(format: variant.metrics.device == nil ? "Processing: %.1f seconds" : "Inference: %.1f seconds", seconds)) }
                            if let loading = variant.metrics.load_seconds { Text(String(format: "Shared model loading: %.1f seconds", loading)) }
                            if let n = variant.metrics.triangles ?? variant.metrics.surface_triangles { Text("Surface triangles: \(n)") }
                            if let n = variant.metrics.cross_pair_supported_pixels { Text("Cross-pair supported samples: \(n)") }
                            if let mm = variant.metrics.native_depth_agreement_mm { Text(String(format: "Native depth difference: %.2f mm · not an accuracy bound", mm)) }
                            if let scale = variant.metrics.scale_dispersion { Text(String(format: "Depth scale dispersion: %.1f%% · uncalibrated", scale * 100)) }
                            if let device = variant.metrics.device { Text("Mac model device: \(device)") }
                            Text("Same saved input. Some methods use a bounded subset of views. No method has a verified physical fit.")
                        }.font(.caption).frame(maxWidth: .infinity, alignment: .leading)
                    }.frame(maxHeight: 150)
                }
                if variant.printable {
                    Toggle("This matches the missing exterior", isOn: $model.comparisonReviewed).font(.subheadline)
                        .accessibilityIdentifier("reviewComparison")
                    Button("Export exterior test piece") { model.exportComparison() }
                        .buttonStyle(.borderedProminent).controlSize(.large)
                        .disabled(!model.comparisonReviewed || model.busy).accessibilityIdentifier("exportComparison")
                } else {
                    Text("\(model.comparison?.variants.filter(\.printable).count ?? 0) methods produced a closed exterior candidate. Choose another method to inspect its result.")
                        .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
                }
            } else { ProgressView("Loading comparison…") }
        }
        .onAppear {
            if model.selectedComparisonID == nil, let id = model.comparison?.suggested_variant_id { model.selectComparison(id) }
        }
    }
}
