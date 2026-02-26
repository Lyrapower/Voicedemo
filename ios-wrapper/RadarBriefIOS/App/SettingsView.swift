import SwiftUI

final class AppConfigStore: ObservableObject {
    @Published var baseURL: String
    private let overrideKey = "BaseURLOverride"

    let devURL: String
    let prodURL: String

    init() {
        let cfg = Bundle.main.infoDictionary
        self.devURL = (cfg?["DEV_URL"] as? String) ?? "http://127.0.0.1:8000/dashboard"
        self.prodURL = (cfg?["PROD_URL"] as? String) ?? "https://YOUR_DOMAIN"
        let fallback = (cfg?["BASE_URL"] as? String) ?? devURL
        self.baseURL = UserDefaults.standard.string(forKey: overrideKey) ?? fallback
    }

    func save(_ value: String) {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        UserDefaults.standard.set(trimmed, forKey: overrideKey)
        baseURL = trimmed
    }

    func resetToDev() {
        UserDefaults.standard.set(devURL, forKey: overrideKey)
        baseURL = devURL
    }
}

struct SettingsView: View {
    @EnvironmentObject var config: AppConfigStore
    @Environment(\.dismiss) private var dismiss
    @State private var inputURL = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Base URL") {
                    TextField("http://127.0.0.1:8000/dashboard", text: $inputURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled(true)
                    Button("Save") {
                        config.save(inputURL)
                        dismiss()
                    }
                    Button("Use DEV_URL") {
                        config.resetToDev()
                        dismiss()
                    }
                }

                Section("Preset") {
                    Text("DEV: \(config.devURL)")
                        .font(.footnote)
                    Text("PROD: \(config.prodURL)")
                        .font(.footnote)
                }
            }
            .navigationTitle("Settings")
            .onAppear { inputURL = config.baseURL }
        }
    }
}

#Preview {
    SettingsView()
        .environmentObject(AppConfigStore())
}
