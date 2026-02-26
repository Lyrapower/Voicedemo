import SwiftUI

@main
struct RadarBriefIOSApp: App {
    @StateObject private var config = AppConfigStore()
    @State private var showSettings = ProcessInfo.processInfo.arguments.contains("--show-settings")

    var body: some Scene {
        WindowGroup {
            NavigationStack {
                ContentView()
                    .environmentObject(config)
                    .sheet(isPresented: $showSettings) {
                        SettingsView()
                            .environmentObject(config)
                    }
            }
        }
    }
}
