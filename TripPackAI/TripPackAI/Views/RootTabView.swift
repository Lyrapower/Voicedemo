import SwiftUI

struct RootTabView: View {
    @StateObject private var api = TripAPIClient()
    @Environment(\.scenePhase) private var phase
    @AppStorage("trippack_debug_auto_refresh") private var autoRefreshDebug: Bool = true

    @State private var selectedTab: Int = {
        let v = ProcessInfo.processInfo.environment["TRIPPACK_START_TAB"]?.lowercased() ?? ""
        if v == "deals" { return 1 }
        if v == "settings" { return 2 }
        return 0
    }()

    var body: some View {
        TabView(selection: $selectedTab) {
            WatchListView()
                .tag(0)
                .tabItem { Label("Watch", systemImage: "dot.scope") }
            DealsListView()
                .tag(1)
                .tabItem { Label("Deals", systemImage: "bell") }
            SettingsView()
                .tag(2)
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
        .environmentObject(api)
        .tint(TripPack.ocean)
        .onAppear {
            Task {
                await api.fetchGoals()
                await api.fetchProviderStatus()
                await api.fetchAlerts()
                #if DEBUG
                await api.ensureDemoDataOnLaunchIfNeeded()
                #endif
            }
        }
        .onReceive(Timer.publish(every: 20, on: .main, in: .common).autoconnect()) { _ in
            #if DEBUG
            guard autoRefreshDebug else { return }
            Task {
                await api.fetchGoals()
                await api.fetchProviderStatus()
                await api.fetchAlerts()
            }
            #endif
        }
    }
}

#if DEBUG
extension RootTabView {
    static var preview: some View { RootTabView() }
}
#endif
