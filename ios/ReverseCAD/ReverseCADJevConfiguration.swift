import Foundation
import ReverseCADCore

enum ReverseCADJevConfiguration {
    /// Generated only for the user's personal build; the resource is excluded from Git.
    static func apiKey(bundle: Bundle = .main) throws -> String {
        struct Configuration: Decodable { let apiKey: String }
        guard let url = bundle.url(forResource: "ReverseCADJevConfig", withExtension: "plist"),
              let data = try? Data(contentsOf: url),
              let config = try? PropertyListDecoder().decode(Configuration.self, from: data) else {
            throw JevClientError.missingKey
        }
        let key = config.apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty, !key.contains("\n"), !key.contains("\r") else { throw JevClientError.missingKey }
        return key
    }
}
