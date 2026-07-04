import Foundation

final class TalkTracksLoader {
    private let fileName = "talk_tracks"
    private let fileExtension = "yaml"

    func load() -> TalkTracks {
        if let overrides = loadFromUserOverrides() {
            return overrides
        }
        if let bundled = loadFromBundleYAML() {
            return bundled
        }
        // fallback: empty modes with some safe defaults
        return TalkTracks(modes: [
            ConversationMode.pitch.rawValue: TalkTrackModeConfig(bullets: [
                "强调产品的核心价值和独特优势，而不是堆砌功能。",
                "用一句话说明和竞品的关键差异。",
                "用具体场景说明 ROI，而不是抽象概念。"
            ]),
            ConversationMode.qa.rawValue: TalkTrackModeConfig(bullets: [
                "先直接、简洁地回答问题，然后再补充细节。",
                "承认不确定的地方，但给出明确的下一步。",
                "避免防御性语气，保持开放和合作。"
            ]),
            ConversationMode.negotiation.rawValue: TalkTrackModeConfig(bullets: [
                "先确认对方关切点，再提出让步边界。",
                "用长期合作价值替代短期价格拉扯。",
                "提出 2–3 个备选方案让对方选择。"
            ]),
            ConversationMode.sales.rawValue: TalkTrackModeConfig(bullets: [
                "优先说客户收益，而不是自己产品多强。",
                "用具体数字或案例支撑，而不是空泛形容词。",
                "引导到下一步行动，例如试点、POC 或小范围上线。"
            ])
        ])
    }

    private func documentsURL() -> URL? {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
    }

    private func overridesURL() -> URL? {
        documentsURL()?.appendingPathComponent("talk_tracks_overrides.json")
    }

    private func loadFromUserOverrides() -> TalkTracks? {
        guard let url = overridesURL(), FileManager.default.fileExists(atPath: url.path) else {
            return nil
        }
        do {
            let data = try Data(contentsOf: url)
            let decoded = try JSONDecoder().decode(TalkTracks.self, from: data)
            return decoded
        } catch {
            print("Failed to load user overrides: \(error)")
            return nil
        }
    }

    func saveToUserOverrides(_ tracks: TalkTracks) {
        guard let url = overridesURL() else { return }
        do {
            let data = try JSONEncoder().encode(tracks)
            try data.write(to: url)
        } catch {
            print("Failed to save user overrides: \(error)")
        }
    }

    private func loadFromBundleYAML() -> TalkTracks? {
        guard let url = Bundle.main.url(forResource: fileName, withExtension: fileExtension) else {
            return nil
        }
        do {
            let text = try String(contentsOf: url, encoding: .utf8)
            return parseYAML(text: text)
        } catch {
            print("Failed to read bundled talk_tracks.yaml: \(error)")
            return nil
        }
    }

    // 极简 YAML 解析，仅支持当前 talk_tracks.yaml 的固定结构
    private func parseYAML(text: String) -> TalkTracks? {
        var modes: [String: TalkTrackModeConfig] = [:]
        var currentModeKey: String?
        var currentBullets: [String] = []

        func flushCurrentMode() {
            if let key = currentModeKey {
                modes[key] = TalkTrackModeConfig(bullets: currentBullets)
            }
            currentModeKey = nil
            currentBullets = []
        }

        for rawLine in text.components(separatedBy: .newlines) {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            if line.hasSuffix(":") {
                let key = String(line.dropLast())
                switch key.lowercased() {
                case "modes":
                    continue
                case "pitch", "qa", "negotiation", "sales":
                    flushCurrentMode()
                    currentModeKey = key
                default:
                    continue
                }
            } else if line.hasPrefix("- ") {
                let bullet = String(line.dropFirst(2))
                currentBullets.append(bullet)
            }
        }
        flushCurrentMode()

        if modes.isEmpty { return nil }
        return TalkTracks(modes: modes)
    }
}

