import SwiftUI

struct DealsListView: View {
    @EnvironmentObject var api: TripAPIClient
    @Environment(\.openURL) private var openURL

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: TripPack.sectionGap) {
                    if let e = api.lastError, !e.isEmpty {
                        Text(e)
                            .font(.caption)
                            .foregroundStyle(.red)
                            .padding(TripPack.cardPadding)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(TripPack.card)
                            .clipShape(RoundedRectangle(cornerRadius: TripPack.cardRadius, style: .continuous))
                    }

                    if api.alerts.isEmpty {
                        Text("No deals yet. Your watch is still checking.")
                            .font(.body)
                            .foregroundStyle(TripPack.textSecondary)
                            .padding(.horizontal, TripPack.horizontalPadding)
                            .padding(.top, 24)
                    }

                    ForEach(api.alerts) { a in
                        dealCard(a)
                    }
                }
                .padding(.horizontal, TripPack.horizontalPadding)
                .padding(.vertical, 12)
            }
            .background(TripPack.background.ignoresSafeArea())
            .navigationTitle("Deals")
            .onAppear { Task { await api.fetchAlerts() } }
            .onChange(of: api.refreshGeneration) { _, _ in Task { await api.fetchAlerts() } }
        }
    }

    private func dealCard(_ a: DealAlertDTO) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(a.title)
                    .font(.headline)
                    .foregroundStyle(a.is_read ? TripPack.textSecondary : TripPack.textPrimary)
                Spacer()
                if !a.is_read {
                    Circle()
                        .fill(TripPack.ocean)
                        .frame(width: 8, height: 8)
                        .accessibilityLabel("Unread")
                }
            }
            Text(a.why_triggered)
                .font(.subheadline)
                .foregroundStyle(TripPack.textSecondary)
            Text(RelativeTime.activityPhrase(since: a.created_at))
                .font(.caption)
                .foregroundStyle(TripPack.textSecondary)
            if a.is_demo {
                Text("Demo data — provider not connected.")
                    .font(.caption2)
                    .foregroundStyle(TripPack.textSecondary)
            }
            if let s = a.source_url, let u = URL(string: s), !s.isEmpty {
                Button("Open source link") {
                    openURL(u)
                }
                .font(.subheadline)
                .accessibilityLabel("Open source link for deal")
            }
        }
        .padding(TripPack.cardPadding)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(TripPack.card)
        .clipShape(RoundedRectangle(cornerRadius: TripPack.cardRadius, style: .continuous))
        .tripCardShadow()
        .contentShape(Rectangle())
        .onTapGesture {
            if !a.is_read {
                Task {
                    await api.readAlert(aid: a.id)
                    await api.fetchAlerts()
                }
            }
        }
    }
}
