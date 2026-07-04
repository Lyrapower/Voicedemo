import SwiftUI

struct WatchListView: View {
    @EnvironmentObject var api: TripAPIClient
    @State private var showNew = false
    @State private var path: [TripGoalDTO] = []

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: TripPack.sectionGap) {
                    if let e = api.lastError, !e.isEmpty {
                        Text(e)
                            .font(.subheadline)
                            .foregroundStyle(.red)
                            .padding(TripPack.cardPadding)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(TripPack.card)
                            .clipShape(RoundedRectangle(cornerRadius: TripPack.cardRadius, style: .continuous))
                            .tripCardShadow()
                    }

                    heroCard

                    if api.goals.isEmpty {
                        Text("No Trip Watch yet. Tap + to add your target.")
                            .font(.body)
                            .foregroundStyle(TripPack.textSecondary)
                            .padding(.horizontal, TripPack.horizontalPadding)
                    }

                    ForEach(api.goals) { g in
                        NavigationLink(value: g) {
                            watchRow(g)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, TripPack.horizontalPadding)
                .padding(.vertical, 12)
            }
            .background(TripPack.background.ignoresSafeArea())
            .navigationTitle("Watch")
            .toolbar {
                Button {
                    showNew = true
                } label: {
                    Image(systemName: "plus.circle.fill")
                }
                .accessibilityLabel("New Trip Watch")
            }
            .sheet(isPresented: $showNew) { NewWatchForm() }
            .navigationDestination(for: TripGoalDTO.self) { g in
                WatchDetailView(goal: g)
            }
            .onAppear {
                #if DEBUG
                if ProcessInfo.processInfo.environment["TRIPPACK_OPEN_FIRST_GOAL"] == "1",
                   path.isEmpty,
                   let first = api.goals.first {
                    path = [first]
                }
                #endif
            }
            .onChange(of: api.goals) { _, goals in
                #if DEBUG
                if ProcessInfo.processInfo.environment["TRIPPACK_OPEN_FIRST_GOAL"] == "1",
                   path.isEmpty,
                   let first = goals.first {
                    path = [first]
                }
                #endif
            }
        }
    }

    private var heroCard: some View {
        ZStack(alignment: .bottomLeading) {
            LinearGradient(
                colors: [
                    Color(red: 0.93, green: 0.96, blue: 0.99),
                    Color(red: 0.88, green: 0.94, blue: 0.98),
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            VStack(alignment: .leading, spacing: 8) {
                Text("Trip Watch")
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(TripPack.navy)
                    .minimumScaleFactor(0.85)
                Text("Watching trips that fit your target.")
                    .font(.subheadline)
                    .foregroundStyle(TripPack.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(TripPack.cardPadding + 4)
        }
        .frame(maxWidth: .infinity, minHeight: 120, alignment: .leading)
        .clipShape(RoundedRectangle(cornerRadius: TripPack.cardRadius, style: .continuous))
        .tripCardShadow()
        .accessibilityElement(children: .combine)
    }

    private func watchRow(_ g: TripGoalDTO) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(g.destination_preference.isEmpty ? "Destination" : g.destination_preference)
                .font(.headline)
                .foregroundStyle(TripPack.textPrimary)
            Text("\(g.start_date) – \(g.end_date)")
                .font(.caption)
                .foregroundStyle(TripPack.textSecondary)
            HStack {
                Text("Budget $\(Int(g.budget_usd))")
                    .font(.caption)
                    .foregroundStyle(TripPack.ocean)
                Spacer()
                Text(g.status == "active" ? "Active" : "Paused")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(g.status == "active" ? TripPack.passGreen : TripPack.textSecondary)
            }
        }
        .padding(TripPack.cardPadding)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(TripPack.card)
        .clipShape(RoundedRectangle(cornerRadius: TripPack.cardRadius, style: .continuous))
        .tripCardShadow()
    }
}

struct NewWatchForm: View {
    @EnvironmentObject var api: TripAPIClient
    @Environment(\.dismiss) private var dismiss
    @State private var o = ""
    @State private var d = ""
    @State private var ds = ""
    @State private var de = ""
    @State private var b = 3500.0
    @State private var car = false

    var body: some View {
        NavigationStack {
            Form {
                TextField("Origin", text: $o)
                TextField("Destination preference", text: $d)
                TextField("Start date (YYYY-MM-DD)", text: $ds)
                TextField("End date (YYYY-MM-DD)", text: $de)
                TextField("Budget (USD)", value: $b, format: .number)
                Toggle("Rental car", isOn: $car)
            }
            .navigationTitle("New Trip Watch")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Create") { Task { await create() } }
                }
            }
        }
    }

    private func create() async {
        let body = TripGoalCreateBody(
            origin: o,
            destination_preference: d,
            budget_usd: b,
            start_date: ds,
            end_date: de,
            needs_car: car,
            status: "active"
        )
        try? await api.createGoal(body)
        await api.fetchGoals()
        dismiss()
    }
}
