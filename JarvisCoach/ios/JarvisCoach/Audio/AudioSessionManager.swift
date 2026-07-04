import AVFoundation

final class AudioSessionManager {
    private let audioEngine = AVAudioEngine()

    var inputNode: AVAudioInputNode {
        audioEngine.inputNode
    }

    func start() {
        configureSession()
        startEngineIfNeeded()
    }

    func stop() {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
    }

    private func configureSession() {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .defaultToSpeaker])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            print("Audio session config error: \(error)")
        }
    }

    private func startEngineIfNeeded() {
        guard !audioEngine.isRunning else { return }
        do {
            try audioEngine.start()
        } catch {
            print("Audio engine start error: \(error)")
        }
    }

    func installTap(bufferHandler: @escaping (AVAudioPCMBuffer, AVAudioTime) -> Void) {
        let format = inputNode.outputFormat(forBus: 0)
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format, block: bufferHandler)
    }
}

