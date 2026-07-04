import SwiftUI

@main
struct JarvisCoachApp: App {
    @StateObject private var sessionViewModel = SessionViewModel()

    var body: some Scene {
        WindowGroup {
            HomeView()
                .environmentObject(sessionViewModel)
        }
    }
}

