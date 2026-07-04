import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var api: TripAPIClient
    @AppStorage("trippack_debug_auto_refresh") private var autoRefreshDebug: Bool = true
    @State private var healthOk = false

    var body: some View {
        NavigationStack {
            Form {
                Section("TripPackAI") {
                    TextField("Backend base URL", text: $api.baseURL, axis: .horizontal)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    if !AppConfig.isDebugBuild, api.baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        Text("Set your backend URL to connect. Localhost is not preset in Release builds.")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                    Button("Refresh status") {
                        Task { await refresh() }
                    }
                    .accessibilityLabel("Refresh connection status")
                    Text("Health: \(healthOk ? "OK" : (api.healthSummary))")
                        .font(.subheadline)
                        .foregroundStyle(TripPack.textSecondary)
                    if let p = api.providerStatus {
                        Text("Provider mode: \(p.provider_mode)")
                            .font(.subheadline)
                        if let m = p.message {
                            Text(m)
                                .font(.caption)
                                .foregroundStyle(TripPack.textSecondary)
                        }
                    } else {
                        Text("Provider mode: —")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    Text("App build: \(AppConfig.isDebugBuild ? "Debug" : "Release")")
                        .font(.caption)
                        .foregroundStyle(TripPack.textSecondary)
                }

                Section("Disclaimer") {
                    Text("Prices can change. Final booking price is confirmed by the provider.")
                        .font(.footnote)
                        .foregroundStyle(TripPack.textSecondary)
                }

                #if DEBUG
                Section("Dev Console") {
                    Toggle("Auto-refresh every 20s", isOn: $autoRefreshDebug)
                    Button("Seed Demo") {
                        Task { await api.seedDemoGoalAndCheck() }
                    }
                    .accessibilityLabel("Seed demo Trip Watch and run check")
                    Button("Check Now (first goal)") {
                        Task {
                            await api.fetchGoals()
                            if let id = api.goals.first?.id {
                                _ = try? await api.checkNow(id: id)
                                await api.fetchGoals()
                                await api.fetchAlerts()
                                api.refreshGeneration += 1
                            }
                        }
                    }
                    if let m = api.lastDevActionMessage, !m.isEmpty {
                        Text(m)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Text("health → \(api.healthDebug)")
                        .font(.caption2)
                        .textSelection(.enabled)
                    Text("provider → \(api.providerDebug)")
                        .font(.caption2)
                        .textSelection(.enabled)
                    Text("goals → \(api.tripGoalsDebug)")
                        .font(.caption2)
                        .textSelection(.enabled)
                    Text("alerts → \(api.alertsDebug)")
                        .font(.caption2)
                        .textSelection(.enabled)
                    if let e = api.lastError, !e.isEmpty {
                        Text(e)
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                }
                #endif
            }
            .navigationTitle("Settings")
            .onAppear {
                Task { await refresh() }
            }
        }
    }

    private func refresh() async {
        healthOk = await api.fetchHealth()
        await api.fetchProviderStatus()
        await api.fetchGoals()
        await api.fetchAlerts()
    }
}
