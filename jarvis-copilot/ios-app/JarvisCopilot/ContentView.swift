import SwiftUI

struct ContentView: View {
    @StateObject private var audioEngine = AudioEngine()
    @StateObject private var wsClient = WebSocketClient()
    @State private var isRecording = false

    var body: some View {
        ZStack {
            VStack(spacing: 20) {
                Text("Jarvis Copilot")
                    .font(.largeTitle)
                    .bold()

                Button(action: toggleRecording) {
                    Image(systemName: isRecording ? "stop.circle.fill" : "mic.circle.fill")
                        .resizable()
                        .frame(width: 80, height: 80)
                        .foregroundColor(isRecording ? .red : .blue)
                }

                Text(isRecording ? "Recording..." : "Tap to start")
                    .font(.headline)
            }

            // HUD Overlay
            HUDView(
                transcript: audioEngine.transcript,
                suggestions: wsClient.suggestions
            )
        }
        .onAppear {
            wsClient.connect()
            audioEngine.onTranscript = { text, speaker in
                wsClient.sendTranscript(text: text, speaker: speaker)
            }
        }
    }

    private func toggleRecording() {
        if isRecording {
            audioEngine.stopRecording()
        } else {
            audioEngine.startRecording()
        }
        isRecording.toggle()
    }
}

