import Foundation
import Speech
import AVFoundation

final class SpeechTranscriber: NSObject, ObservableObject {
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US")) // locale is a hint; recognition can still handle mixed content
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?

    private var transcriptBuffer: [String] = []
    private var lastStableUtterance: String = ""
    private var lastUpdateTime: Date = Date()

    /// 回调：当检测到稳定的 utterance（800ms 无变化或 final）时触发
    var onStableUtterance: ((String, Bool) -> Void)?

    private let stableDebouncer = Debouncer(interval: 0.8)

    func startTranscribing() {
        requestPermissionsIfNeeded { [weak self] granted in
            guard granted else { return }
            DispatchQueue.main.async {
                self?.startRecognition()
            }
        }
    }

    func stopTranscribing() {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionTask?.cancel()
        recognitionTask = nil
        request = nil
    }

    func resetContext() {
        transcriptBuffer.removeAll()
        lastStableUtterance = ""
    }

    func recentTranscriptWindow() -> String {
        let joined = transcriptBuffer.joined(separator: " ")
        // 近似从尾部截取 400 字符以内作为 30–60 秒窗口
        if joined.count > 400 {
            let suffix = joined.suffix(400)
            return String(suffix)
        }
        return joined
    }

    func lastQuestion() -> String {
        // 简单从最近一段话中寻找可能的问题句；去掉问号以规避生成端的问号限制
        let joined = recentTranscriptWindow()
        guard !joined.isEmpty else { return "" }
        return joined
    }

    private func requestPermissionsIfNeeded(completion: @escaping (Bool) -> Void) {
        SFSpeechRecognizer.requestAuthorization { authStatus in
            switch authStatus {
            case .authorized:
                AVAudioSession.sharedInstance().requestRecordPermission { micGranted in
                    completion(micGranted)
                }
            default:
                completion(false)
            }
        }
    }

    private func startRecognition() {
        if recognitionTask != nil {
            recognitionTask?.cancel()
            recognitionTask = nil
        }

        let audioSession = AVAudioSession.sharedInstance()
        do {
            try audioSession.setCategory(.record, mode: .measurement, options: .duckOthers)
            try audioSession.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            print("Speech audio session error: \(error)")
        }

        request = SFSpeechAudioBufferRecognitionRequest()
        guard let request = request else { return }

        request.shouldReportPartialResults = true

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { buffer, when in
            request.append(buffer)
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            print("Audio engine start error: \(error)")
        }

        recognitionTask = recognizer?.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }
            if let result = result {
                let best = result.bestTranscription.formattedString
                self.handleTranscriptUpdate(text: best, isFinal: result.isFinal)
            }
            if error != nil {
                self.stopTranscribing()
            }
        }
    }

    private func handleTranscriptUpdate(text: String, isFinal: Bool) {
        transcriptBuffer.append(text)
        lastUpdateTime = Date()

        if isFinal {
            lastStableUtterance = text
            onStableUtterance?(text, true)
        } else {
            stableDebouncer.execute { [weak self] in
                guard let self = self else { return }
                let elapsed = Date().timeIntervalSince(self.lastUpdateTime)
                if elapsed >= 0.8 {
                    self.lastStableUtterance = text
                    self.onStableUtterance?(text, false)
                }
            }
        }
    }
}

