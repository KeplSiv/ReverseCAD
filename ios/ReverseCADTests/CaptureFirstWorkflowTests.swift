import XCTest
import UIKit
import CoreVideo
import ReverseCADCore
@testable import ReverseCAD

private final class SavedViewProtocol: URLProtocol {
    static var count = 0
    static var status = 200
    static var ambiguous = false
    static var hold = false
    static var stopped = 0
    static var bodies = [[String: Any]]()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.count += 1
        var body = request.httpBody ?? Data()
        if body.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 8192)
            while stream.hasBytesAvailable {
                let n = stream.read(&buffer, maxLength: buffer.count)
                if n <= 0 { break }; body.append(contentsOf: buffer.prefix(n))
            }
        }
        if let object = try? JSONSerialization.jsonObject(with: body) as? [String: Any] { Self.bodies.append(object) }
        if Self.hold { return }
        let data = try! JSONSerialization.data(withJSONObject: ["model": "fixture", "answers": ["present": ["noul": 0.99], "unobstructed": ["noul": 0.99], "instances": ["choice": Self.ambiguous ? "several" : "one", "confidence": 0.99], "category": ["choice": "tool", "confidence": 0.99], "target": ["box": ["left": 0.1,"right": 0.9,"top": 0.1,"bottom": 0.9], "confidence": 0.99]]])
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: Self.status, httpVersion: nil, headerFields: Self.status == 429 ? ["Retry-After":"2"] : nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { Self.stopped += 1 }
}

@MainActor final class CaptureFirstWorkflowTests: XCTestCase {
    var root: URL!
    override func setUp() async throws {
        SavedViewProtocol.count = 0; SavedViewProtocol.status = 200; SavedViewProtocol.ambiguous = false; SavedViewProtocol.hold = false; SavedViewProtocol.stopped = 0; SavedViewProtocol.bodies = []
        root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }
    override func tearDown() async throws { try? FileManager.default.removeItem(at: root) }
    func workflow() -> CapturedObjectWorkflow {
        CapturedObjectWorkflow(clientFactory: {
            let c = URLSessionConfiguration.ephemeral; c.protocolClasses = [SavedViewProtocol.self]
            return JevClient(session: URLSession(configuration: c))
        }, keyProvider: { "test-only" })
    }
    func capture() throws -> URL {
        let directory = root.appendingPathComponent("capture")
        let writer = try ScanPackageWriter(directory: directory, manifest: CaptureManifest(scanID: "test", source: "synthetic", device: "test", segments: [CaptureSegment(segmentID: "s")]))
        let image = UIGraphicsImageRenderer(size: CGSize(width: 80,height: 60)).image { c in UIColor.white.setFill(); c.fill(CGRect(x:0,y:0,width:80,height:60)) }.jpegData(compressionQuality: 0.9)!
        for i in 0..<12 {
            var pose = Geometry.identity; pose[12] = Double(i)*0.03
            let f = CaptureFrame(scanID:"test",segmentID:"s",frameID:String(i),timestampS:Double(i),rgbPath:"rgb/\(i).jpg",rgbWidth:80,rgbHeight:60,intrinsics:[50,0,0,0,50,0,40,30,1],intrinsicsWidth:80,intrinsicsHeight:60,worldCamera:pose,trackingState:"normal",quality:CaptureQuality(blurScore:50,accepted:true))
            try writer.append(frame:f,assets:[f.rgbPath:image])
        }
        return try writer.finish()
    }
    func settle(_ value: CapturedObjectWorkflow) async throws {
        for _ in 0..<500 { if !value.working { return }; try await Task.sleep(for: .milliseconds(10)) }
        XCTFail("Workflow did not settle")
    }
    func testSavedSessionReuseBoundedCallsAndTwoImageIdentityRequests() async throws {
        let directory = try capture(), before = try CaptureIO.sha256(file: directory.appendingPathComponent("frames.jsonl"))
        let value = workflow(); value.find(project:root,capture:directory,description:""); try await settle(value)
        XCTAssertEqual(value.phase,"identified"); XCTAssertEqual(SavedViewProtocol.count,10)
        XCTAssertFalse(SavedViewProtocol.bodies.isEmpty)
        let first = try XCTUnwrap(SavedViewProtocol.bodies.first)
        XCTAssertEqual((first["assets"] as? [String:Any])?.count,2)
        let reload = workflow(); reload.load(project:root,capture:directory)
        XCTAssertEqual(reload.phase,"identified"); XCTAssertEqual(SavedViewProtocol.count,10)
        XCTAssertEqual(before,try CaptureIO.sha256(file:directory.appendingPathComponent("frames.jsonl")))
    }
    func testAmbiguousTapUsesSameCaptureAndCanConfirm() async throws {
        let directory = try capture(), value = workflow(); SavedViewProtocol.ambiguous = true
        value.find(project:root,capture:directory,description:""); try await settle(value); XCTAssertEqual(value.phase,"ambiguous")
        SavedViewProtocol.ambiguous = false
        value.find(project:root,capture:directory,description:"",point:CGPoint(x:0.4,y:0.4)); try await settle(value)
        XCTAssertEqual(value.phase,"identified"); XCTAssertEqual(value.identity?.userSelected,true)
    }
    func testAuthenticationRetryAndCancellationPreserveCapture() async throws {
        let directory = try capture(), value = workflow(); SavedViewProtocol.status = 401
        value.find(project:root,capture:directory,description:""); try await settle(value)
        XCTAssertTrue(value.failure?.contains("401") == true); XCTAssertEqual(SavedViewProtocol.count,1)
        SavedViewProtocol.status = 200; SavedViewProtocol.hold = true
        value.find(project:root,capture:directory,description:"")
        try await Task.sleep(for:.milliseconds(80)); value.cancel(); try await Task.sleep(for:.milliseconds(80))
        XCTAssertEqual(value.phase,"idle"); XCTAssertGreaterThan(SavedViewProtocol.stopped,0)
        SavedViewProtocol.hold = false
        value.find(project:root,capture:directory,description:""); try await settle(value); XCTAssertEqual(value.phase,"identified")
        XCTAssertEqual(try CaptureIO.readFrames(directory:directory).count,12)
    }
    func testRateLimitDoesNotRetryUntilCooldown() async throws {
        let directory = try capture(), value = workflow(); SavedViewProtocol.status = 429
        value.find(project:root,capture:directory,description:""); try await settle(value)
        value.find(project:root,capture:directory,description:"")
        XCTAssertEqual(SavedViewProtocol.count,1); XCTAssertTrue(value.failure?.contains("limit") == true)
    }
    func testFloatVisionMaskUsesValuesAndStrides() throws {
        var buffer: CVPixelBuffer?
        XCTAssertEqual(CVPixelBufferCreate(nil,2,2,kCVPixelFormatType_OneComponent32Float,nil,&buffer),kCVReturnSuccess)
        let b = try XCTUnwrap(buffer); CVPixelBufferLockBaseAddress(b,[])
        let raw = CVPixelBufferGetBaseAddress(b)!, stride = CVPixelBufferGetBytesPerRow(b)
        raw.storeBytes(of:Float(1),as:Float.self); raw.storeBytes(of:Float(0),toByteOffset:4,as:Float.self)
        raw.storeBytes(of:Float.nan,toByteOffset:stride,as:Float.self); raw.storeBytes(of:Float(0.9),toByteOffset:stride+4,as:Float.self)
        CVPixelBufferUnlockBaseAddress(b,[])
        XCTAssertEqual(SavedObjectMasks.rasterize(b,width:2,height:2),Data([255,0,0,255]))
    }
}
