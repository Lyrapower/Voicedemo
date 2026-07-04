import Foundation

struct TripGoalDTO: Codable, Identifiable, Hashable {
    let id: String
    var origin: String
    var destination_preference: String
    var budget_usd: Double
    var start_date: String
    var end_date: String
    var needs_car: Bool
    var status: String
    var created_at: String
    var updated_at: String
    var last_checked_at: String?
    var next_check_at: String?
}

struct ProviderQuoteDTO: Codable, Identifiable, Hashable {
    let id: String
    let trip_goal_id: String
    let category: String
    let provider: String
    let title: String
    let price_usd: Double?
    let currency: String
    let source_url: String
    let fetched_at: String
    let terms_notes: String?
    let is_demo: Bool
    let is_live: Bool
}

struct QuotesEnvelope: Codable {
    let items: [ProviderQuoteDTO]
    let provider_status: String
    let message: String?
}

struct PackageSnapshotDTO: Codable, Identifiable, Hashable {
    let id: String
    let trip_goal_id: String
    let total_price_usd: Double?
    let flight_quote_id: String?
    let stay_quote_id: String?
    let car_quote_id: String?
    let passed_budget: Bool?
    let constraints: [String]
    let created_at: String
    let is_demo: Bool
}

struct DealAlertDTO: Codable, Identifiable, Hashable {
    let id: String
    let trip_goal_id: String
    let snapshot_id: String?
    let title: String
    let why_triggered: String
    let source_url: String?
    let is_read: Bool
    let created_at: String
    let is_demo: Bool
}

struct ProviderStatusDTO: Codable, Hashable {
    let provider_mode: String
    let backend_mode: String
    let message: String?
}

struct HealthDTO: Codable {
    let ok: Bool
    let ts: String?
}

struct CheckNowResponseDTO: Codable {
    let ok: Bool?
    let provider_status: String?
    let message: String?
    let error: String?
}

extension TripGoalDTO {
    static var empty: TripGoalDTO {
        .init(
            id: "",
            origin: "",
            destination_preference: "",
            budget_usd: 0,
            start_date: "",
            end_date: "",
            needs_car: false,
            status: "active",
            created_at: "",
            updated_at: "",
            last_checked_at: nil,
            next_check_at: nil
        )
    }
}
