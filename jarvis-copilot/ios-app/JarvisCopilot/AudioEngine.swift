import AVFoundation
import Speech
import Foundation

class AudioEngine: ObservableObject {
    @Published var transcript: [TranscriptItem] = []

    private let audioEngine = AVAudioEngine()
    private let speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?

    var onTranscript: ((String, String) -> Void)?

    func startRecording() {
        SFSpeechRecognizer.requestAuthorization { status in
            guard status == .authorized else { return }

            DispatchQueue.main.async {
                self.setupRecording()
            }
        }
    }

    private func setupRecording() {
        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()

        guard let recognitionRequest = recognitionRequest else { return }

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)

        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { buffer, _ in
            recognitionRequest.append(buffer)
        }

        audioEngine.prepare()

        do {
            try audioEngine.start()
        } catch {
            print("Audio engine error: \(error)")
            return
        }

        recognitionTask = speechRecognizer?.recognitionTask(with: recognitionRequest) { result, error in
            if let result = result {
                let text = result.bestTranscription.formattedString

                // Simple speaker detection: assume user speaking
                let speaker = "user"

                let item = TranscriptItem(text: text, speaker: speaker, timestamp: Date())

                DispatchQueue.main.async {
                    if self.transcript.last?.text != text {
                        self.transcript.append(item)
                        self.onTranscript?(text, speaker)
                    }
                }
            } else if let error = error {
                print("Speech recognition error: \(error)")
            }
        }
    }

    func stopRecording() {
        audioEngine.stop()
        recognitionRequest?.endAudio()
        audioEngine.inputNode.removeTap(onBus: 0)
    }
}

struct TranscriptItem: Identifiable {
    let id = UUID()
    let text: String
    let speaker: String
    let timestamp: Date
}

