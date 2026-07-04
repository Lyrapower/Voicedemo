import SwiftUI

struct HomeView: View {
    @EnvironmentObject var session: SessionViewModel
    @State private var showHUD = false
    @State private var showScriptLibrary = false
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("JarvisCoach")
                        .font(.largeTitle.bold())
                    Text("实时对话军师提词器")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 16)

                VStack(spacing: 16) {
                    BigCard(
                        title: "Start Session",
                        subtitle: "进入实时 HUD，开始对话军师",
                        systemImage: "dot.radiowaves.left.and.right",
                        action: {
                            session.startSession()
                            showHUD = true
                        }
                    )

                    Picker("Mode", selection: $session.mode) {
                        ForEach(ConversationMode.allCases) { mode in
                            Text(mode.displayName).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)

                    Picker("Language", selection: $session.language) {
                        ForEach(ConversationLanguage.allCases) { lang in
                            Text(lang.displayName).tag(lang)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                VStack(spacing: 12) {
                    BigCard(
                        title: "Talk Tracks",
                        subtitle: "配置每个模式下的话术要点",
                        systemImage: "list.bullet.rectangle.portrait",
                        action: { showScriptLibrary = true }
                    )

                    BigCard(
                        title: "Settings",
                        subtitle: "调节高级选项与实验功能",
                        systemImage: "gear",
                        action: { showSettings = true }
                    )
                }

                Spacer()
            }
            .padding(.horizontal, 20)
            .navigationDestination(isPresented: $showHUD) {
                LiveHUDView()
                    .navigationBarBackButtonHidden(true)
            }
            .navigationDestination(isPresented: $showScriptLibrary) {
                ScriptLibraryView()
            }
            .navigationDestination(isPresented: $showSettings) {
                SettingsView()
            }
        }
    }
}

