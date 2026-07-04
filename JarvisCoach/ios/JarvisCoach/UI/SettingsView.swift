import SwiftUI

struct SettingsView: View {
    @AppStorage("allowAskBackInQAMode") private var allowAskBackInQAMode: Bool = false

    var body: some View {
        Form {
            Section("Q&A 模式") {
                Toggle("允许在 Q&A 模式下适度反问", isOn: $allowAskBackInQAMode)
                Text("默认关闭。开启后仅在 Q&A 模式下，Claude 可以偶尔给出一个简短的反问以澄清问题。")
                    .font(.footnote)
                    .foregroundColor(.secondary)
            }

            Section("隐私与安全") {
                Text("JarvisCoach 不会将完整转写内容持久化到磁盘，仅在 Debug 折叠区短暂显示最近一句。")
                    .font(.footnote)
            }
        }
        .navigationTitle("Settings")
    }
}

