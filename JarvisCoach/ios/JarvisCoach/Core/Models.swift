import Foundation
import SwiftUI

enum ConversationMode: String, CaseIterable, Identifiable, Codable {
    case pitch
    case qa
    case negotiation
    case sales

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .pitch: return "Pitch"
        case .qa: return "Q&A"
        case .negotiation: return "Negotiation"
        case .sales: return "Sales"
        }
    }
}

enum ConversationLanguage: String, CaseIterable, Identifiable, Codable {
    case auto
    case en
    case zh

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .auto: return "Auto"
        case .en: return "EN"
        case .zh: return "ZH"
        }
    }
}

enum SpeakerRole: String, CaseIterable, Identifiable {
    case them
    case me

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .them: return "Them"
        case .me: return "Me"
        }
    }
}

struct SuggestionState {
    var text: String = ""
    var lastUpdated: Date?
    var lastLatency: TimeInterval?
    var isLoading: Bool = false
    var lastError: String?
}

struct TalkTrackModeConfig: Codable {
    var bullets: [String]
}

struct TalkTracks: Codable {
    var modes: [String: TalkTrackModeConfig]
}

enum ClaudeConnectionState {
    case idle
    case ok
    case unavailable(String)
}

final class SessionViewModel: ObservableObject {
    @Published var mode: ConversationMode = .pitch
    @Published var language: ConversationLanguage = .auto
    @Published var speakerRole: SpeakerRole = .them

    @Published var suggestion = SuggestionState()
    @Published var lastUtterance: String = ""

    @Published var claudeState: ClaudeConnectionState = .idle

    @Published var isPaused: Bool = false

    @Published var talkTracks: TalkTracks = TalkTracks(modes: [:])

    private let audioManager = AudioSessionManager()
    private let speechTranscriber = SpeechTranscriber()
    private let anthropicClient = AnthropicClient()
    private let debouncer = Debouncer(interval: 0.8)

    private var lastAPICallDate: Date?

    init() {
        bindTranscriber()
        loadDefaultTalkTracks()
    }

    func startSession() {
        isPaused = false
        suggestion.lastError = nil
        suggestion.isLoading = false
        suggestion.text = ""
        lastUtterance = ""
        claudeState = .idle
        audioManager.start()
        speechTranscriber.startTranscribing()
    }

    func stopSession() {
        audioManager.stop()
        speechTranscriber.stopTranscribing()
    }

    func togglePause() {
        isPaused.toggle()
    }

    func applyShorter() {
        Task { @MainActor in
            await requestSuggestion(forceShorter: true, moreDirect: false)
        }
    }

    func applyMoreDirect() {
        Task { @MainActor in
            await requestSuggestion(forceShorter: false, moreDirect: true)
        }
    }

    func resetContext() {
        lastUtterance = ""
        suggestion = SuggestionState()
        speechTranscriber.resetContext()
    }

    func clearDebug() {
        lastUtterance = ""
    }

    private func bindTranscriber() {
        speechTranscriber.onStableUtterance = { [weak self] utterance, isFinal in
            guard let self else { return }
            DispatchQueue.main.async {
                self.lastUtterance = utterance
            }
            guard self.speakerRole == .them, !self.isPaused else { return }

            self.debouncer.execute { [weak self] in
                Task { @MainActor in
                    await self?.requestSuggestion(forceShorter: false, moreDirect: false)
                }
            }
        }
    }

    @MainActor
    private func requestSuggestion(forceShorter: Bool, moreDirect: Bool) async {
        let now = Date()
        if let last = lastAPICallDate, now.timeIntervalSince(last) < 1.2 {
            return
        }
        lastAPICallDate = now

        let transcriptWindow = speechTranscriber.recentTranscriptWindow()
        let lastQuestion = speechTranscriber.lastQuestion()
        let bullets = talkTracksForCurrentMode()

        let (systemPrompt, userContent) = PromptBuilder.build(
            mode: mode,
            language: language,
            bullets: bullets,
            recentTranscript: transcriptWindow,
            lastQuestion: lastQuestion,
            forceShorter: forceShorter,
            moreDirect: moreDirect
        )

        suggestion.isLoading = true
        let startTime = Date()
        do {
            let reply = try await anthropicClient.generateSuggestion(
                systemPrompt: systemPrompt,
                userContent: userContent
            )
            let latency = Date().timeIntervalSince(startTime)
            withAnimation(.easeInOut(duration: 0.25)) {
                self.suggestion.text = reply
                self.suggestion.lastUpdated = Date()
                self.suggestion.lastLatency = latency
                self.suggestion.isLoading = false
                self.suggestion.lastError = nil
                self.claudeState = .ok
            }
        } catch {
            self.suggestion.isLoading = false
            self.suggestion.lastError = error.localizedDescription
            self.claudeState = .unavailable("AI temporarily unavailable")
        }
    }

    private func loadDefaultTalkTracks() {
        let loader = TalkTracksLoader()
        self.talkTracks = loader.load()
    }

    func saveTalkTracks(_ updated: TalkTracks) {
        self.talkTracks = updated
        TalkTracksLoader().saveToUserOverrides(updated)
    }

    func talkTracksForCurrentMode() -> [String] {
        if let config = talkTracks.modes[mode.rawValue] {
            return config.bullets
        }
        return []
    }
}

