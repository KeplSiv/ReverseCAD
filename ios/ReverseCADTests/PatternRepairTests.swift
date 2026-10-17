import XCTest
import ReverseCADCore
@testable import ReverseCAD

@MainActor
final class PatternRepairTests: XCTestCase {
    private func fixture() throws -> (AppModel, URL) {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let model = AppModel(rootURL: root)
        model.create(name: "General repair test", synthetic: true)
        let dir = try XCTUnwrap(model.projectDirectory)
        let revision = dir.appendingPathComponent("revisions/test")
        try FileManager.default.createDirectory(at: revision, withIntermediateDirectories: true)
        let preview = try JSONEncoder().encode(MeshPreview(vertices: [[0,0,0],[1,0,0],[0,1,0]], triangles: [[0,1,2]]))
        let comparisonJSON: [String: Any] = ["schema_version": 1, "scan_id": "same-input", "suggested_variant_id": "tracked", "conclusion": "No verified winner", "variants": [
            ["id": "tracked", "title": "Tracked repair", "method": "tracked", "status": "proposal_needs_review", "message": "Exterior estimate", "part_preview": "pattern_1_solid.json", "print_files": ["pattern_1.stl", "pattern_1.3mf", "pattern_1_validation.json"], "printable": true, "seconds": 2.5, "metrics": [:]] as [String: Any],
            ["id": "failed", "title": "Failed method", "method": "failed", "status": "failed", "message": "No supported output", "print_files": [], "printable": false, "seconds": 1.0, "metrics": [:]] as [String: Any]]]
        let comparisonData = try JSONSerialization.data(withJSONObject: comparisonJSON)
        let files = ["comparison.json": comparisonData, "pattern_1_solid.json": preview, "pattern_1.stl": Data("verified fixture".utf8),
                     "pattern_1.3mf": Data("verified fixture".utf8),
                     "pattern_1_validation.json": Data("{}".utf8), "pattern_hypotheses.json": Data("{}".utf8)]
        let infos = files.map { ArtifactInfo(id: $0.key, name: $0.key, sha256: CaptureIO.sha256($0.value), size: $0.value.count) }
        for (name, data) in files { try data.write(to: revision.appendingPathComponent(name)) }
        let list = try JSONSerialization.jsonObject(with: JSONEncoder().encode(infos.sorted { $0.name < $1.name }))
        try JSONSerialization.data(withJSONObject: ["folder": "revisions/test", "artifacts": list]).write(to: dir.appendingPathComponent("observed_artifacts.json"))
        try JSONSerialization.data(withJSONObject: ["version": 1, "revisionKey": "test", "artifacts": list]).write(to: revision.appendingPathComponent(".verified-artifacts.json"))
        let options = [PatternRepairOption(id: "pattern_1", preview: "pattern_1_solid.json", print_preview: "pattern_1_solid.json", pattern_kind: "reflection", validation: .init(status: "closed_exterior_prototype", watertight: true, files: ["pattern_1.stl", "pattern_1.3mf"]))]
        let optionJSON = try JSONSerialization.jsonObject(with: JSONEncoder().encode(options))
        try JSONSerialization.data(withJSONObject: ["pattern_hypotheses": ["candidates": optionJSON], "comparison": comparisonJSON]).write(to: dir.appendingPathComponent("reconstruction.json"))
        model.loadDerived() // Exercise restored backend results, not direct UI state injection.
        XCTAssertEqual(model.patternRepairs.count, 1)
        return (model, root)
    }
    private func settle(_ model: AppModel) async throws {
        for _ in 0..<100 {
            if !model.busy { return }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTFail("Action did not finish")
    }
    func testSelectReviewAndExportVerifiedCandidate() async throws {
        let (model, root) = try fixture(); defer { try? FileManager.default.removeItem(at: root) }
        model.selectPattern("pattern_1"); try await settle(model)
        XCTAssertNotNil(model.patternMesh, model.error ?? ""); XCTAssertFalse(model.patternReviewed)
        model.exportPattern(); try await settle(model)
        XCTAssertFalse(model.showingShare)
        model.patternReviewed = true
        model.exportPattern(); try await settle(model)
        XCTAssertTrue(model.showingShare); XCTAssertEqual(model.shareURLs.count, 4)
    }
    func testModifiedFileBlocksExportAfterReview() async throws {
        let (model, root) = try fixture(); defer { try? FileManager.default.removeItem(at: root) }
        model.selectPattern("pattern_1"); try await settle(model); XCTAssertNotNil(model.patternMesh, model.error ?? ""); model.patternReviewed = true
        try Data("changed".utf8).write(to: model.projectDirectory!.appendingPathComponent("revisions/test/pattern_1.stl"))
        model.exportPattern(); try await settle(model)
        XCTAssertFalse(model.showingShare); XCTAssertNotNil(model.error)
    }
    func testChangingSelectionClearsReviewAndFailedScanBlocksExport() async throws {
        let (model, root) = try fixture(); defer { try? FileManager.default.removeItem(at: root) }
        model.selectPattern("pattern_1"); try await settle(model); XCTAssertNotNil(model.patternMesh, model.error ?? ""); model.patternReviewed = true
        model.selectPattern("pattern_1"); try await settle(model)
        XCTAssertFalse(model.patternReviewed)
        model.patternReviewed = true; model.scanNeedsRescan = true
        model.exportPattern(); try await settle(model)
        XCTAssertFalse(model.showingShare)
    }
    func testComparisonSwitchingAndReviewedExportFromRestoredResults() async throws {
        let (model, root) = try fixture(); defer { try? FileManager.default.removeItem(at: root) }
        XCTAssertEqual(model.comparison?.scan_id, "same-input")
        model.selectComparison("tracked"); try await settle(model)
        XCTAssertNotNil(model.comparisonPart, model.error ?? "")
        XCTAssertNil(model.comparisonScan)
        model.exportComparison(); try await settle(model)
        XCTAssertFalse(model.showingShare)
        model.comparisonReviewed = true
        model.exportComparison(); try await settle(model)
        XCTAssertTrue(model.showingShare); XCTAssertEqual(model.shareURLs.count, 4)
        model.showingShare = false
        model.selectComparison("failed"); try await settle(model)
        XCTAssertEqual(model.selectedComparisonID, "failed")
        XCTAssertNil(model.comparisonPart); XCTAssertFalse(model.comparisonReviewed)
        model.comparisonReviewed = true
        model.exportComparison(); try await settle(model)
        XCTAssertFalse(model.showingShare)
    }
    func testComparisonModifiedPrintFileBlocksExport() async throws {
        let (model, root) = try fixture(); defer { try? FileManager.default.removeItem(at: root) }
        model.selectComparison("tracked"); try await settle(model)
        XCTAssertNotNil(model.comparisonPart, model.error ?? "")
        model.comparisonReviewed = true
        try Data("changed".utf8).write(to: model.projectDirectory!.appendingPathComponent("revisions/test/pattern_1.stl"))
        model.exportComparison(); try await settle(model)
        XCTAssertFalse(model.showingShare); XCTAssertNotNil(model.error)
    }

}
