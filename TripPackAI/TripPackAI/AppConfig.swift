import Foundation

enum AppConfig {
    /// DEBUG: local simulator default. RELEASE: user must set backend URL in Settings (no bundled localhost).
    static var defaultBackendBaseURL: String {
        #if DEBUG
        return "http://127.0.0.1:8810"
        #else
        return ""
        #endif
    }

    static var isDebugBuild: Bool {
        #if DEBUG
        return true
        #else
        return false
        #endif
    }
}
