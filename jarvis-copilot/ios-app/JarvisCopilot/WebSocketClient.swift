import Foundation

class WebSocketClient: ObservableObject {
    @Published var suggestions: [Suggestion] = []

    private var webSocket: URLSessionWebSocketTask?
    private let url = URL(string: "ws://127.0.0.1:8000/ws")!

    func connect() {
        let session = URLSession(configuration: .default)
        webSocket = session.webSocketTask(with: url)
        webSocket?.resume()

        receiveMessage()
    }

    func sendTranscript(text: String, speaker: String) {
        let message: [String: Any] = [
            "type": "transcript",
            "text": text,
            "speaker": speaker,
            "timestamp": Date().timeIntervalSince1970
        ]

        guard let data = try? JSONSerialization.data(withJSONObject: message),
              let json = String(data: data, encoding: .utf8) else { return }

        webSocket?.send(.string(json)) { error in
            if let error = error {
                print("Send error: \(error)")
            }
        }
    }

    private func receiveMessage() {
        webSocket?.receive { [weak self] result in
            switch result {
            case .success(let message):
                switch message {
                case .string(let text):
                    if let data = text.data(using: .utf8),
                       let suggestion = try? JSONDecoder().decode(Suggestion.self, from: data) {
                        DispatchQueue.main.async {
                            self?.suggestions.append(suggestion)
                        }
                    }
                default:
                    break
                }

                self?.receiveMessage()

            case .failure(let error):
                print("Receive error: \(error)")
            }
        }
    }
}

struct Suggestion: Codable, Identifiable {
    let id = UUID()
    let type: String
    let text: String
    let confidence: Double
    let priority: String
    let reasoning: String

    enum CodingKeys: String, CodingKey {
        case type, text, confidence, priority, reasoning
    }
}

