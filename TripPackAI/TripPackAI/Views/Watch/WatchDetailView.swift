import SwiftUI

struct WatchDetailView: View {
    @EnvironmentObject var api: TripAPIClient
    let goal: TripGoalDTO
    @State private var qenv: QuotesEnvelope?
    @State private var snaps: [PackageSnapshotDTO] = []
    @State private var busy = false
    @State private var checkHint: String?
    @State private var showEdit = false

    private var live: TripGoalDTO {
        api.goals.first(where: { $0.id == goal.id }) ?? goal
    }

    private var mode: String {
        if let st = qenv?.provider_status { return st }
        return api.providerStatus?.provider_mode ?? "NOT_CONNECTED"
    }

    private var disclosure: String? {
        if mode == "DEBUG_DEMO" { return "Demo data — provider not connected." }
        if mode == "NOT_CONNECTED" { return "Provider not connected. No live quotes shown." }
        return nil
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: TripPack.sectionGap) {
                statusCard
                if let d = disclosure {
                    Text(d)
                        .font(.subheadline)
                        .foregroundStyle(TripPack.textSecondary)
                        .padding(TripPack.cardPadding)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(TripPack.card)
                        .clipShape(RoundedRectangle(cornerRadius: TripPack.cardRadius, style: .continuous))
                        .tripCardShadow()
                }
                if let hint = checkHint {
                    Text(hint)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                quoteSections
                packageSection
            }
            .padding(.horizontal, TripPack.horizontalPadding)
            .padding(.vertical, 12)
        }
        .background(TripPack.background.ignoresSafeArea())
        .navigationTitle(live.destination_preference)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button("Edit") { showEdit = true }
                    .accessibilityLabel("Edit Trip Watch")
            }
            ToolbarItem(placement: .bottomBar) {
                HStack {
                    Button {
                        Task { await runCheck() }
                    } label: {
                        if busy { ProgressView() } else { Text("Check Now") }
                    }
                    .disabled(busy)
                    .buttonStyle(.borderedProminent)
                    .tint(TripPack.ocean)
                    .accessibilityLabel("Check Now")

                    if live.status == "active" {
                        Button("Pause") { Task { await pause() } }
                            .accessibilityLabel("Pause Trip Watch")
                    } else {
                        Button("Resume") { Task { await resume() } }
                            .accessibilityLabel("Resume Trip Watch")
                    }
                }
            }
        }
        .sheet(isPresented: $showEdit) {
            EditWatchForm(goal: live)
        }
        .task { await load() }
        .onChange(of: api.refreshGeneration) { _, _ in Task { await load() } }
    }

    private var statusCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Active watch")
                .font(.caption.weight(.semibold))
                .foregroundStyle(TripPack.ocean)
            Text("\(live.origin) → \(live.destination_preference)")
                .font(.headline)
            Text("Budget $\(Int(live.budget_usd)) · \(live.start_date) – \(live.end_date)")
                .font(.subheadline)
                .foregroundStyle(TripPack.textSecondary)
            Divider().opacity(0.35)
            Text("Provider: \(mode.replacingOccurrences(of: "_", with: " "))")
                .font(.subheadline)
            Text(RelativeTime.updatedPhrase(since: live.updated_at))
                .font(.caption)
                .foregroundStyle(TripPack.textSecondary)
            if let n = RelativeTime.nextCheckPhrase(until: live.next_check_at) {
                Text(n)
                    .font(.caption)
                    .foregroundStyle(TripPack.textSecondary)
            }
        }
        .padding(TripPack.cardPadding)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(TripPack.card)
        .clipShape(RoundedRectangle(cornerRadius: TripPack.cardRadius, style: .continuous))
        .tripCardShadow()
    }

    @ViewBuilder
    private var quoteSections: some View {
        if mode == "NOT_CONNECTED", (qenv?.items.isEmpty ?? true) {
            EmptyView()
        } else if let env = qenv, !env.items.isEmpty {
            bestCard(title: "Best current option — flight", quote: env.items.first { $0.category == "flight" })
            bestCard(title: "Best current option — stay", quote: env.items.first { $0.category == "stay" })
            if live.needs_car {
                bestCard(title: "Best current option — car", quote: env.items.first { $0.category == "car" })
            }
        }
    }

    private func bestCard(title: String, quote: ProviderQuoteDTO?) -> some View {
        Group {
            if let q = quote {
                VStack(alignment: .leading, spacing: 8) {
                    Text(title)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(TripPack.ocean)
                    Text(q.title)
                        .font(.headline)
                    if let p = q.price_usd {
                        Text("$\(Int(p)) \(q.currency)")
                            .font(.title3.weight(.semibold))
                    } else {
                        Text("—")
                            .foregroundStyle(.secondary)
                    }
                    if let t = q.terms_notes, !t.isEmpty {
                        Text(t)
                            .font(.caption2)
                            .foregroundStyle(TripPack.textSecondary)
                    }
                    if let u = URL(string: q.source_url), !q.source_url.isEmpty {
                        Link("Open source link", destination: u)
                            .font(.subheadline)
                    }
                }
                .padding(TripPack.cardPadding)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(TripPack.card)
                .clipShape(RoundedRectangle(cornerRadius: TripPack.cardRadius, style: .continuous))
                .tripCardShadow()
            }
        }
    }

    @ViewBuilder
    private var packageSection: some View {
        if let s = snaps.first {
            VStack(alignment: .leading, spacing: 10) {
                Text("Current package estimate")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(TripPack.ocean)
                if let t = s.total_price_usd {
                    Text("$\(Int(t)) total (estimate)")
                        .font(.title3.weight(.semibold))
                } else {
                    Text("—")
                        .foregroundStyle(.secondary)
                }
                Text("Prices can change. Final booking price is confirmed by the provider.")
                    .font(.caption2)
                    .foregroundStyle(TripPack.textSecondary)
                if s.is_demo {
                    Text("Demo data — provider not connected.")
                        .font(.caption2)
                        .foregroundStyle(TripPack.textSecondary)
                }
                if !s.constraints.isEmpty {
                    Text("Constraints / why not selected")
                        .font(.caption.weight(.semibold))
                        .padding(.top, 4)
                    ForEach(s.constraints.prefix(5), id: \.self) { c in
                        Text("• \(c)")
                            .font(.caption)
                            .foregroundStyle(TripPack.textPrimary)
                    }
                }
            }
            .padding(TripPack.cardPadding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(TripPack.passTint.opacity(0.5))
            .clipShape(RoundedRectangle(cornerRadius: TripPack.cardRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: TripPack.cardRadius, style: .continuous)
                    .stroke(TripPack.passGreen.opacity(0.2), lineWidth: 1)
            )
            .tripCardShadow()
        }
    }

    private func load() async {
        do {
            qenv = try await api.fetchQuotes(gid: live.id)
            snaps = try await api.fetchSnapshots(gid: live.id)
        } catch {
            qenv = nil
            snaps = []
        }
    }

    private func runCheck() async {
        busy = true
        checkHint = nil
        defer { busy = false }
        do {
            let r = try await api.checkNow(id: live.id)
            if let m = r.message { checkHint = m }
            await load()
            await api.fetchGoals()
            await api.fetchAlerts()
        } catch {
            checkHint = "Check Now could not complete. Try again when the backend is available."
        }
    }

    private func pause() async {
        try? await api.pause(id: live.id)
        await api.fetchGoals()
    }

    private func resume() async {
        try? await api.resume(id: live.id)
        await api.fetchGoals()
    }
}

struct EditWatchForm: View {
    @EnvironmentObject var api: TripAPIClient
    @Environment(\.dismiss) private var dismiss
    let goal: TripGoalDTO
    @State private var o: String = ""
    @State private var d: String = ""
    @State private var ds: String = ""
    @State private var de: String = ""
    @State private var b: Double = 0
    @State private var car: Bool = false

    var body: some View {
        NavigationStack {
            Form {
                TextField("Origin", text: $o)
                TextField("Destination preference", text: $d)
                TextField("Start", text: $ds)
                TextField("End", text: $de)
                TextField("Budget", value: $b, format: .number)
                Toggle("Rental car", isOn: $car)
            }
            .navigationTitle("Edit watch")
            .onAppear {
                o = goal.origin
                d = goal.destination_preference
                ds = goal.start_date
                de = goal.end_date
                b = goal.budget_usd
                car = goal.needs_car
            }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save() } }
                }
            }
        }
    }

    private func save() async {
        let patch: [String: Any] = [
            "origin": o,
            "destination_preference": d,
            "start_date": ds,
            "end_date": de,
            "budget_usd": b,
            "needs_car": car,
        ]
        try? await api.patchGoal(id: goal.id, patch: patch)
        await api.fetchGoals()
        dismiss()
    }
}
