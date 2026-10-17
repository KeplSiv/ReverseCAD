import XCTest
import ReverseCADCore
@testable import ReverseCAD

final class VerifiedArtifactsTests: XCTestCase {
    private func fixture() throws -> (URL, [ArtifactInfo]) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("verified-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let files = [("artifact-one", "part.step", Data("ISO-10303-21;\nEND-ISO-10303-21;".utf8)),
                     ("artifact-two", "parameters.json", Data("{\"unit\":\"mm\"}".utf8))]
        let infos = files.map { ArtifactInfo(id: $0.0, name: $0.1, sha256: CaptureIO.sha256($0.2), size: $0.2.count) }
        for file in files { try file.2.write(to: directory.appendingPathComponent(file.1)) }
        let sorted = infos.sorted { $0.name < $1.name }
        let manifest: [String: Any] = ["version": 1, "revisionKey": "repair-r1", "artifacts": sorted.map {
            ["id": $0.id, "name": $0.name, "sha256": $0.sha256, "size": $0.size] as [String: Any]
        }]
        try JSONSerialization.data(withJSONObject: manifest).write(to: directory.appendingPathComponent(".verified-artifacts.json"))
        return (directory, infos)
    }

    func testCompleteRevisionVerifiesRegardlessOfInputOrder() throws {
        let (directory, infos) = try fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        XCTAssertNoThrow(try VerifiedArtifactStore.verify(infos: infos.reversed(), directory: directory))
    }

    func testModifiedFileFailsEvenWhenByteCountIsUnchanged() throws {
        let (directory, infos) = try fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        try Data(repeating: 65, count: infos[0].size).write(to: directory.appendingPathComponent(infos[0].name))
        XCTAssertThrowsError(try VerifiedArtifactStore.verify(infos: infos, directory: directory))
    }

    func testMissingUnexpectedAndSymlinkedArtifactsFailClosed() throws {
        let (directory, infos) = try fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent(infos[0].name)
        let original = try Data(contentsOf: file)
        try FileManager.default.removeItem(at: file)
        XCTAssertThrowsError(try VerifiedArtifactStore.verify(infos: infos, directory: directory))
        try original.write(to: file)
        let extra = directory.appendingPathComponent("unverified.stl")
        try Data([0]).write(to: extra)
        XCTAssertThrowsError(try VerifiedArtifactStore.verify(infos: infos, directory: directory))
        try FileManager.default.removeItem(at: extra)
        try FileManager.default.removeItem(at: file)
        try FileManager.default.createSymbolicLink(at: file, withDestinationURL: directory.appendingPathComponent(infos[1].name))
        XCTAssertThrowsError(try VerifiedArtifactStore.verify(infos: infos, directory: directory))
    }

    func testUnsafeDuplicateAndDifferentRevisionEntriesAreRejected() throws {
        let (directory, infos) = try fixture()
        defer { try? FileManager.default.removeItem(at: directory) }
        for name in ["../part.step", "/tmp/part.step", "nested/part.step", "part\\step", ".verified-artifacts.json"] {
            let unsafe = ArtifactInfo(id: "safe-id", name: name, sha256: infos[0].sha256, size: infos[0].size)
            XCTAssertThrowsError(try VerifiedArtifactStore.verify(infos: [unsafe], directory: directory))
        }
        XCTAssertThrowsError(try VerifiedArtifactStore.verify(infos: infos + [infos[0]], directory: directory))
        let changedID = ArtifactInfo(id: "different-revision", name: infos[0].name, sha256: infos[0].sha256, size: infos[0].size)
        XCTAssertThrowsError(try VerifiedArtifactStore.verify(infos: [changedID, infos[1]], directory: directory))
    }

    func testExistingVerifiedRevisionIsReusedWithoutNetworkOrMutation() async throws {
        let (directory, infos) = try fixture()
        let base = FileManager.default.temporaryDirectory.appendingPathComponent("exports-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: base) }
        let published = base.appendingPathComponent("repair-r1")
        try FileManager.default.moveItem(at: directory, to: published)
        let client = ServiceClient(baseURL: URL(string: "http://127.0.0.1:1")!, token: "test")
        let result = try await VerifiedArtifactStore.download(infos: infos, baseDirectory: base, revisionKey: "repair-r1", client: client)
        XCTAssertEqual(result.standardizedFileURL.path, published.standardizedFileURL.path)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: base.path), ["repair-r1"])
        XCTAssertNoThrow(try VerifiedArtifactStore.verify(infos: infos, directory: result))
    }

    func testExistingCorruptedRevisionIsNeverOverwritten() async throws {
        let (directory, infos) = try fixture()
        let base = FileManager.default.temporaryDirectory.appendingPathComponent("exports-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: base) }
        let published = base.appendingPathComponent("repair-r1")
        try FileManager.default.moveItem(at: directory, to: published)
        let damaged = Data("changed".utf8)
        let file = published.appendingPathComponent(infos[0].name)
        try damaged.write(to: file)
        let client = ServiceClient(baseURL: URL(string: "http://127.0.0.1:1")!, token: "test")
        do {
            _ = try await VerifiedArtifactStore.download(infos: infos, baseDirectory: base, revisionKey: "repair-r1", client: client)
            XCTFail("A corrupted published revision must not be accepted or overwritten")
        } catch { }
        XCTAssertEqual(try Data(contentsOf: file), damaged)
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: base.path), ["repair-r1"])
    }

    func testFailedNewDownloadPreservesPublishedRevisionAndRemovesStage() async throws {
        let (directory, infos) = try fixture()
        let base = FileManager.default.temporaryDirectory.appendingPathComponent("exports-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: base) }
        let published = base.appendingPathComponent("repair-r1")
        try FileManager.default.moveItem(at: directory, to: published)
        let originals = try infos.map { try Data(contentsOf: published.appendingPathComponent($0.name)) }
        let client = ServiceClient(baseURL: URL(string: "http://127.0.0.1:1")!, token: "test")
        do {
            _ = try await VerifiedArtifactStore.download(infos: infos, baseDirectory: base, revisionKey: "repair-r2", client: client)
            XCTFail("An unreachable server must not publish a new revision")
        } catch { }
        XCTAssertNoThrow(try VerifiedArtifactStore.verify(infos: infos, directory: published))
        for (info, original) in zip(infos, originals) {
            XCTAssertEqual(try Data(contentsOf: published.appendingPathComponent(info.name)), original)
        }
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: base.path), ["repair-r1"], "No partial revision or receiving stage may remain")
    }
}
