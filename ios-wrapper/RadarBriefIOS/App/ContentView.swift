import SwiftUI

struct ContentView: View {
    @EnvironmentObject var config: AppConfigStore
    @State private var showSettings = false

    var body: some View {
        WebView(urlString: config.baseURL)
            .ignoresSafeArea(edges: .bottom)
            .navigationTitle("RadarBrief")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Settings") {
                        showSettings = true
                    }
                }
            }
            .sheet(isPresented: $showSettings) {
                SettingsView()
                    .environmentObject(config)
            }
    }
}

#Preview {
    ContentView()
        .environmentObject(AppConfigStore())
}
