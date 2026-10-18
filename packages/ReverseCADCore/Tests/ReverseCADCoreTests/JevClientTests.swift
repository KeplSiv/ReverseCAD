import XCTest
@testable import ReverseCADCore

private final class JevStubProtocol: URLProtocol {
    static var status = 200
    static var headers = [String: String]()
    static var response = Data()
    static var received: URLRequest?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.received = request
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: Self.status,
            httpVersion: nil, headerFields: Self.headers)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Self.response)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

final class JevClientTests: XCTestCase {
    private func reply(presence: Double = 0.98, instances: String = "one", left: Double = 0.2) throws -> Data {
        try JSONSerialization.data(withJSONObject: ["model": "jev-1.14.0", "answers": [
            "present": ["noul": presence], "instances": ["choice": instances, "confidence": 0.95],
            "category": ["choice": "mechanical_part", "confidence": 0.96],
            "target": ["box": ["left": left, "right": 0.8, "top": 0.1, "bottom": 0.9], "confidence": 0.94]]])
    }
    private func client(status: Int = 200, headers: [String: String] = [:], response: Data = Data()) -> JevClient {
        JevStubProtocol.status = status; JevStubProtocol.headers = headers; JevStubProtocol.response = response
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [JevStubProtocol.self]
        return JevClient(session: URLSession(configuration: config))
    }

    func testDirectAuthenticatedRequestNeedsNoCompanionSettings() async throws {
        let client = client(response: try reply()), id = UUID(), photo = Data([1,2,3])
        let result = try await client.identify(jpeg: photo, description: "the black bracket", requestID: id, apiKey: "test-only-key")
        let request = try XCTUnwrap(JevStubProtocol.received)
        XCTAssertEqual(request.url?.absoluteString, "https://api.typesafe.ai/v1/systemone")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer test-only-key")
        XCTAssertEqual(request.value(forHTTPHeaderField: "TypeSafe-Danger-Zone-Images"), "true")
        let payload = try client.makeRequest(jpeg: photo, description: "the black bracket", apiKey: "test-only-key")
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: payload.httpBody!) as? [String: Any])
        XCTAssertEqual((body["questions"] as? [String: Any])?.count, 4)
        XCTAssertEqual((body["assets"] as? [String: Any])?.count, 1)
        XCTAssertEqual(result.requestID, id); XCTAssertNotNil(result.box)
        XCTAssertEqual(result.objectRecord["transport"] as? String, "direct_iphone_to_typesafe")
    }

    func testAbsentAmbiguousAndMalformedBoxesAreRejected() throws {
        for data in [try reply(presence: 0.1), try reply(instances: "several")] {
            XCTAssertNil(try JevClient.interpret(data: data, jpeg: Data([1]), description: "bracket", requestID: UUID()).box)
        }
        XCTAssertThrowsError(try JevClient.interpret(data: reply(left: 0.95), jpeg: Data([1]), description: "bracket", requestID: UUID()))
        XCTAssertThrowsError(try JevClient.interpret(data: Data("{}".utf8), jpeg: Data([1]), description: "bracket", requestID: UUID()))
    }

    func testActionableErrorsDoNotExposeProviderBodyOrKeepRetryingBadCredentials() async throws {
        for (code, expected) in [(401, JevClientError.authentication), (402, .credits), (403, .accessDenied), (400, .unavailable(400))] {
            let client = client(status: code, response: Data("private-provider-body".utf8))
            do {
                _ = try await client.identify(jpeg: Data([1]), description: "bracket", requestID: UUID(), apiKey: "test-only-key")
                XCTFail("Expected provider status error")
            } catch let error as JevClientError {
                XCTAssertEqual(error, expected); XCTAssertFalse(error.shouldRetry)
                XCTAssertFalse(error.localizedDescription.contains("private-provider-body"))
            }
        }
    }

    func testRateLimitDelayIsAppliedToSchedule() async throws {
        let client = client(status: 429, headers: ["Retry-After": "30"])
        do {
            _ = try await client.identify(jpeg: Data([1]), description: "bracket", requestID: UUID(), apiKey: "test-only-key")
            XCTFail("Expected rate limit")
        } catch let error as JevClientError {
            XCTAssertEqual(error, .rateLimited(30)); XCTAssertTrue(error.shouldRetry)
            var schedule = LiveIdentificationSchedule(); schedule.start(at: 0)
            schedule.failed(at: 0, retryAfter: error.retryAfter)
            XCTAssertNil(schedule.reserve(at: 29.9)); XCTAssertNotNil(schedule.reserve(at: 30))
        }
    }

    func testOptInLiveTypeSafeRequest() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let keyPath = env["JEV_LIVE_TEST_KEY_FILE"], let imagePath = env["JEV_LIVE_TEST_IMAGE"] else {
            throw XCTSkip("Real provider check requires explicit key and fixture paths.")
        }
        let key = try String(contentsOfFile: keyPath).trimmingCharacters(in: .whitespacesAndNewlines)
        let jpeg = try Data(contentsOf: URL(fileURLWithPath: imagePath)), started = Date()
        let detection = try await JevClient().identify(jpeg: jpeg,
            description: "the rectangular block in the center of the image", requestID: UUID(), apiKey: key)
        XCTAssertNotNil(detection.box); XCTAssertEqual(detection.instances, "one")
        print("DIRECT_JEV_OK model=\(detection.model) category=\(detection.category) latency_ms=\(Int(Date().timeIntervalSince(started)*1000))")
    }
}
