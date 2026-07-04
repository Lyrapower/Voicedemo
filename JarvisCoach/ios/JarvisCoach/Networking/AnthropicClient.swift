import Foundation

enum AnthropicClientError: Error {
    case missingAPIKey
    case invalidResponse
}

final class AnthropicClient {
    private let session: URLSession
    private let model = "claude-3-sonnet-20240229"
    private let maxTokens: Int = 60
    private let temperature: Double = 0.2

    init(session: URLSession = .shared) {
        self.session = session
    }

    func generateSuggestion(systemPrompt: String, userContent: String) async throws -> String {
        guard let apiKey = ProcessInfo.processInfo.environment["ANTHROPIC_API_KEY"] ??
                Bundle.main.object(forInfoDictionaryKey: "ANTHROPIC_API_KEY") as? String else {
            throw AnthropicClientError.missingAPIKey
        }

        var request = URLRequest(url: URL(string: "https://api.anthropic.com/v1/messages")!)
        request.httpMethod = "POST"
        request.timeoutInterval = 10
        request.addValue("application/json", forHTTPHeaderField: "Content-Type")
        request.addValue(apiKey, forHTTPHeaderField: "x-api-key")
        request.addValue("2023-06-01", forHTTPHeaderField: "anthropic-version")

        let body: [String: Any] = [
            "model": model,
            "max_tokens": maxTokens,
            "temperature": temperature,
            "system": systemPrompt,
            "messages": [
                [
                    "role": "user",
                    "content": [
                        [
                            "type": "text",
                            "text": userContent
                        ]
                    ]
                ]
            ]
        ]

        request.httpBody = try JSONSerialization.data(withJSONObject: body, options: [])

        let (data, response) = try await session.data(for: request)

        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw AnthropicClientError.invalidResponse
        }

        let decoded = try JSONSerialization.jsonObject(with: data, options: []) as? [String: Any]
        if let content = (decoded?["content"] as? [[String: Any]])?.first,
           let text = content["text"] as? String {
            return text.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        // 兼容新的 content 结构：[{ "type": "text", "text": "..." }]
        if let rawContent = decoded?["content"] as? [[String: Any]] {
            let texts = rawContent.compactMap { $0["text"] as? String }
            if let joined = texts.first {
                return joined.trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }

        throw AnthropicClientError.invalidResponse
    }
}

