import Foundation

public enum JSONValue: Codable, Sendable, Equatable {
    case object([String:JSONValue]), array([JSONValue]), string(String), number(Double), bool(Bool), null
    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { self = .object(try c.decode([String:JSONValue].self)) }
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self { case .object(let v): try c.encode(v); case .array(let v): try c.encode(v); case .string(let v): try c.encode(v); case .number(let v): try c.encode(v); case .bool(let v): try c.encode(v); case .null: try c.encodeNil() }
    }
    public subscript(_ key: String) -> JSONValue? { object?[key] }
    public var object: [String:JSONValue]? { if case .object(let x) = self { return x }; return nil }
    public var array: [JSONValue]? { if case .array(let x) = self { return x }; return nil }
    public var string: String? { if case .string(let x) = self { return x }; return nil }
    public var double: Double? { if case .number(let x) = self { return x }; return nil }
    public var int: Int? { guard let d = double, d.isFinite, d >= Double(Int.min), d < Double(Int.max), d.rounded() == d else { return nil }; return Int(d) }
    public var bool: Bool? { if case .bool(let x) = self { return x }; return nil }
}

public struct ServiceClient: @unchecked Sendable {
    public let baseURL: URL
    private let token: String
    private let session: URLSession
    public init(baseURL: URL, token: String, session: URLSession = .shared) { self.baseURL=baseURL; self.token=token; self.session=session }
    private func makeRequest(_ method: String, _ path: String) throws -> URLRequest {
        guard ["http","https"].contains(baseURL.scheme?.lowercased() ?? ""), baseURL.host != nil, baseURL.user == nil, baseURL.password == nil, baseURL.query == nil, baseURL.fragment == nil else { throw CoreError.invalid("Use a service URL such as http://192.168.1.10:8767 without credentials or query parameters.") }
        guard path.hasPrefix("/v1/"), !path.contains(".."), !path.contains("?"), !path.contains("#"), !path.contains("%"), !path.contains("\\") else { throw CoreError.invalid("Invalid service route.") }
        var url = baseURL
        for component in path.split(separator: "/") { url.appendPathComponent(String(component)) }
        var request = URLRequest(url: url, timeoutInterval: (path.hasSuffix("cad/review") || path.hasSuffix("/reason")) ? 90 : 45)
        request.httpMethod=method; request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization"); request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }
    private func check(_ response: URLResponse, body: Data = Data()) throws {
        guard let response = response as? HTTPURLResponse else { throw CoreError.invalid("Service did not return HTTP.") }
        guard (200..<300).contains(response.statusCode) else {
            let description = String(data: body.prefix(4096), encoding: .utf8) ?? "Request failed. Check the service address and pairing token."
            throw CoreError.service(response.statusCode, description)
        }
    }
    public func data(_ method: String, _ path: String, body: Data? = nil) async throws -> Data {
        try Task.checkCancellation()
        guard (body?.count ?? 0) <= 32*1024*1024 else { throw CoreError.limit("Service JSON request exceeds 32 MiB.") }
        var request = try makeRequest(method,path); request.httpBody=body
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        let (data,response) = try await session.data(for: request)
        try check(response,body:data)
        guard data.count <= 64*1024*1024 else { throw CoreError.limit("Service response exceeds 64 MiB.") }
        return data
    }
    public func request(_ method: String, _ path: String, body: JSONValue? = nil) async throws -> JSONValue {
        let response = try await data(method,path,body:try body.map { try CaptureIO.encoder().encode($0) })
        return response.isEmpty ? .null : try JSONDecoder().decode(JSONValue.self,from:response)
    }
    /// Missing-hash resume is safe across app restarts because scan_id remains stable.
    public func uploadScan(directory: URL, projectID: String? = nil) async throws -> String {
        try Task.checkCancellation()
        let manifest = try ScanPackageWriter.validate(directory: directory, allowIncomplete: true)
        _ = try CaptureIO.validatedRelativePath(manifest.scanID)
        guard !manifest.scanID.contains("/") else { throw CoreError.invalid("Scan identifier cannot contain a slash.") }
        var createBody: [String:JSONValue] = ["scan_id":.string(manifest.scanID),"source":.string(manifest.source)]
        if let projectID { createBody["project_id"] = .string(projectID) }
        let created = try await request("POST","/v1/scans",body:.object(createBody))
        guard created["scan_id"]?.string == manifest.scanID else { throw CoreError.integrity("Service returned a different scan identifier.") }
        let state = try await request("GET","/v1/scans/\(manifest.scanID)")
        var remote: [String:String] = [:]
        for asset in state["assets"]?.array ?? [] { if let path = asset["path"]?.string, let hash = asset["sha256"]?.string { remote[path]=hash } }
        for file in try CaptureIO.files(directory: directory) {
            try Task.checkCancellation()
            let hash = try CaptureIO.sha256(file:file.url)
            if remote[file.path] == hash { continue }
            var request = try makeRequest("PUT","/v1/scans/\(manifest.scanID)/assets/\(file.path)")
            request.setValue("application/octet-stream",forHTTPHeaderField:"Content-Type")
            request.setValue(hash,forHTTPHeaderField:"X-Content-SHA256")
            request.timeoutInterval=120
            var lastError: Error?
            for attempt in 0..<3 {
                do { let (body,response) = try await session.upload(for:request,fromFile:file.url); try check(response,body:body); lastError=nil; break }
                catch let error as URLError where [.networkConnectionLost,.timedOut,.cannotConnectToHost,.notConnectedToInternet].contains(error.code) {
                    lastError=error; if attempt < 2 { try await Task.sleep(nanoseconds:UInt64(attempt+1)*400_000_000) }
                }
            }
            if let lastError { throw lastError }
        }
        _ = try await request("POST","/v1/scans/\(manifest.scanID)/commit")
        return manifest.scanID
    }
    public func downloadArtifact(id: String, to destination: URL, expectedSHA256: String? = nil) async throws -> URL {
        try Task.checkCancellation()
        _ = try CaptureIO.validatedRelativePath(id)
        guard !id.contains("/") else { throw CoreError.invalid("Invalid artifact identifier.") }
        let request = try makeRequest("GET","/v1/artifacts/\(id)")
        let (temporary,response) = try await session.download(for:request)
        defer { try? FileManager.default.removeItem(at:temporary) }
        try check(response)
        let size = try temporary.resourceValues(forKeys:[.fileSizeKey]).fileSize ?? 0
        guard size <= CaptureIO.maximumPackageBytes else { throw CoreError.limit("Artifact exceeds 512 MiB.") }
        if let expectedSHA256, try CaptureIO.sha256(file:temporary) != expectedSHA256 { throw CoreError.integrity("Downloaded artifact checksum does not match this revision.") }
        try Task.checkCancellation()
        try FileManager.default.createDirectory(at:destination.deletingLastPathComponent(),withIntermediateDirectories:true)
        let stage = destination.deletingLastPathComponent().appendingPathComponent(".download-"+UUID().uuidString)
        try FileManager.default.copyItem(at:temporary,to:stage)
        do {
            if FileManager.default.fileExists(atPath:destination.path) { _ = try FileManager.default.replaceItemAt(destination,withItemAt:stage) }
            else { try FileManager.default.moveItem(at:stage,to:destination) }
        } catch { try? FileManager.default.removeItem(at:stage); throw error }
        return destination
    }
}
