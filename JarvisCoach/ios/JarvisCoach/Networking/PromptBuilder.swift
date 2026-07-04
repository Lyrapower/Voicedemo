import Foundation

enum PromptBuilder {
    static func build(
        mode: ConversationMode,
        language: ConversationLanguage,
        bullets: [String],
        recentTranscript: String,
        lastQuestion: String,
        forceShorter: Bool,
        moreDirect: Bool
    ) -> (system: String, user: String) {
        let modeLabel: String
        switch mode {
        case .pitch: modeLabel = "产品 Pitch 场景"
        case .qa: modeLabel = "Q&A 问答场景"
        case .negotiation: modeLabel = "商务谈判场景"
        case .sales: modeLabel = "销售沟通场景"
        }

        let langInstruction: String
        switch language {
        case .auto:
            langInstruction = "使用中文为主，必要时自然地夹带英文专业术语（如 pitch / ROI / moat）。"
        case .en:
            langInstruction = "主要使用自然的英文回答，必要时可以穿插少量中文词语。"
        case .zh:
            langInstruction = "使用自然流畅的中文回答，必要时自然地夹带英文专业术语。"
        }

        var styleModifiers: [String] = []
        if forceShorter {
            styleModifiers.append("本次回答要明显更短、更精炼。")
        }
        if moreDirect {
            styleModifiers.append("本次回答要更加直接、去掉多余铺垫。")
        }

        let styleExtra = styleModifiers.joined(separator: " ")

        let system = """
你是用户身边的实时对话军师，场景是\(modeLabel)。
核心要求：
1. 只输出最多两句完整的话，不要输出条目符号或编号。
2. 默认**禁止使用问号**，不要反问、不要说“可以这样回答吗”等，直接给出最优回答版本。
3. 第一句必须是直接回答当前对方问题或话题。
4. 第二句（如果需要）用于补充价值、下一步建议或提议后续行动，例如“建议下一步…”，也不能出现问号。
5. 不要提到“作为 AI 模型”之类的表述，不讨论自己的身份。
6. 语气要专业、自信、克制，不夸张营销。
\(langInstruction)
\(styleExtra)

请确保最终输出中不包含任何问号字符“？”或“?”。
"""

        let bulletsJoined = bullets.prefix(5).joined(separator: "\n- ")
        let tracksSection = bulletsJoined.isEmpty ? "（当前模式暂无预设话术，可直接根据对话回答。）" : "- " + bulletsJoined

        let user = """
【最近 30–60 秒对话摘录】
\(recentTranscript)

【对方最近问题或核心关切】
\(lastQuestion)

【当前模式话术要点（仅供参考，不要逐字照读）】
\(tracksSection)

请根据以上内容，直接给出我下一句应该说的话（最多两句），严格遵守系统提示中的所有约束。
"""

        return (system, user)
    }
}

