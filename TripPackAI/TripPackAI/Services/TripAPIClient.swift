import Foundation
import SwiftUI

struct TripGoalCreateBody: Encodable {
    var origin: String
    var destination_preference: String
    var budget_usd: Double
    var start_date: String
    var end_date: String
    var needs_car: Bool
    var status: String
}

@MainActor
final class TripAPIClient: ObservableObject {
    @AppStorage("trippack_base_url") var baseURL: String = AppConfig.defaultBackendBaseURL

    @Published var lastError: String?
    @Published var lastDevActionMessage: String?
    @Published var refreshGeneration: Int = 0
    @Published var providerStatus: ProviderStatusDTO?
    @Published var goals: [TripGoalDTO] = []
    @Published var alerts: [DealAlertDTO] = []
    @Published var healthSummary: String = "—"

    #if DEBUG
    @Published var healthDebug: String = "—"
    @Published var providerDebug: String = "—"
    @Published var tripGoalsDebug: String = "—"
    @Published var alertsDebug: String = "—"
    #endif

    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()
    private let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 25
        c.timeoutIntervalForResource = 35
        c.waitsForConnectivity = false
        return URLSession(configuration: c)
    }()

    private func normalizedBase() -> String {
        var s = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        while s.hasSuffix("/") { s.removeLast() }
        if s.isEmpty, !AppConfig.defaultBackendBaseURL.isEmpty {
            return AppConfig.defaultBackendBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return s
    }

    private func url(_ path: String) throws -> URL {
        let b = normalizedBase()
        let p = path.hasPrefix("/") ? path : "/" + path
        guard let u = URL(string: b + p) else { throw URLError(.badURL) }
        return u
    }

    private func recordRequestError(_ path: String, _ error: Error) {
        lastError = "\(path): \(error.localizedDescription)"
    }

    private func preview(_ data: Data) -> String {
        let text = String(data: data, encoding: .utf8) ?? ""
        return String(text.prefix(200))
    }

    #if DEBUG
    private func setDebug(_ endpoint: String, url: URL, status: Int?, data: Data?) {
        let statusPart = status.map { "\($0)" } ?? "ERR"
        let bodyPart = data.map(preview) ?? ""
        let line = "\(url.absoluteString) | \(statusPart) | \(bodyPart)"
        switch endpoint {
        case "/health": healthDebug = line
        case "/provider-status": providerDebug = line
        case "/trip-goals": tripGoalsDebug = line
        case "/alerts": alertsDebug = line
        default: break
        }
    }
    #endif

    private func dataGET(_ path: String) async throws -> Data {
        var req = URLRequest(url: try url(path))
        req.httpMethod = "GET"
        do {
            let (data, res) = try await session.data(for: req)
            let http = res as? HTTPURLResponse
            #if DEBUG
            setDebug(path, url: req.url!, status: http?.statusCode, data: data)
            #endif
            if let c = http?.statusCode, c >= 400 {
                lastError = "Request failed (\(c))."
                throw URLError(.badServerResponse)
            }
            return data
        } catch {
            #if DEBUG
            setDebug(path, url: req.url!, status: nil, data: nil)
            #endif
            recordRequestError(path, error)
            throw error
        }
    }

    private func voidPOST(_ path: String) async throws {
        var req = URLRequest(url: try url(path))
        req.httpMethod = "POST"
        let (data, res) = try await session.data(for: req)
        let http = res as? HTTPURLResponse
        if let c = http?.statusCode, c >= 400 {
            lastError = String(data: data, encoding: .utf8).flatMap { $0.count < 200 ? $0 : nil }
                ?? "Request failed (\(c))."
            throw URLError(.badServerResponse)
        }
    }

    private func jsonPOST(_ path: String, _ enc: some Encodable) async throws {
        var req = URLRequest(url: try url(path))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try encoder.encode(enc)
        let (data, res) = try await session.data(for: req)
        let http = res as? HTTPURLResponse
        if let c = http?.statusCode, c >= 400 {
            lastError = String(data: data, encoding: .utf8).flatMap { $0.count < 200 ? $0 : nil }
                ?? "Request failed (\(c))."
            throw URLError(.badServerResponse)
        }
    }

    func fetchHealth() async -> Bool {
        lastError = nil
        do {
            let d = try await dataGET("/health")
            let h = try decoder.decode(HealthDTO.self, from: d)
            healthSummary = h.ok ? "OK" : "Fail"
            return h.ok
        } catch {
            healthSummary = "Unreachable"
            return false
        }
    }

    func fetchProviderStatus() async {
        do {
            let d = try await dataGET("/provider-status")
            providerStatus = try decoder.decode(ProviderStatusDTO.self, from: d)
        } catch {
            providerStatus = nil
        }
    }

    func fetchGoals() async {
        do {
            let d = try await dataGET("/trip-goals")
            goals = try decoder.decode([TripGoalDTO].self, from: d)
        } catch {
            goals = []
        }
    }

    func fetchAlerts() async {
        do {
            let d = try await dataGET("/alerts")
            alerts = try decoder.decode([DealAlertDTO].self, from: d)
        } catch {
            alerts = []
        }
    }

    func createGoal(_ b: TripGoalCreateBody) async throws {
        try await jsonPOST("/trip-goals", b)
    }

    func patchGoal(id: String, patch: [String: Any]) async throws {
        var req = URLRequest(url: try url("/trip-goals/\(id)"))
        req.httpMethod = "PATCH"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: patch)
        let (data, res) = try await session.data(for: req)
        if let h = res as? HTTPURLResponse, h.statusCode >= 400 {
            lastError = "Could not save changes."
            throw URLError(.badServerResponse)
        }
        _ = data
    }

    func checkNow(id: String) async throws -> CheckNowResponseDTO {
        var req = URLRequest(url: try url("/trip-goals/\(id)/check-now"))
        req.httpMethod = "POST"
        let (data, res) = try await session.data(for: req)
        if let h = res as? HTTPURLResponse, h.statusCode >= 400 {
            lastError = "Check Now could not complete."
            throw URLError(.badServerResponse)
        }
        return (try? decoder.decode(CheckNowResponseDTO.self, from: data))
            ?? CheckNowResponseDTO(ok: true, provider_status: nil, message: nil, error: nil)
    }

    func fetchQuotes(gid: String) async throws -> QuotesEnvelope {
        let d = try await dataGET("/trip-goals/\(gid)/quotes")
        return try decoder.decode(QuotesEnvelope.self, from: d)
    }

    func fetchSnapshots(gid: String) async throws -> [PackageSnapshotDTO] {
        let d = try await dataGET("/trip-goals/\(gid)/snapshots")
        return try decoder.decode([PackageSnapshotDTO].self, from: d)
    }

    func pause(id: String) async throws { try await voidPOST("/trip-goals/\(id)/pause") }

    func resume(id: String) async throws { try await voidPOST("/trip-goals/\(id)/resume") }

    func readAlert(aid: String) async {
        do {
            var req = URLRequest(url: try url("/alerts/\(aid)/read"))
            req.httpMethod = "PATCH"
            let (_, res) = try await session.data(for: req)
            if let h = res as? HTTPURLResponse, h.statusCode >= 400 { lastError = "Could not mark read." }
        } catch { recordRequestError("/alerts/\(aid)/read", error) }
    }

    #if DEBUG
    func seedDemoGoalAndCheck() async {
        lastError = nil
        lastDevActionMessage = nil
        let body = TripGoalCreateBody(
            origin: "San Diego",
            destination_preference: "Maui",
            budget_usd: 5000,
            start_date: "2026-06-01",
            end_date: "2026-06-10",
            needs_car: true,
            status: "active"
        )
        do {
            try await createGoal(body)
            await fetchGoals()
            guard let gid = goals.first?.id else {
                lastError = "Seed: no goal returned."
                return
            }
            _ = try await checkNow(id: gid)
            await fetchGoals()
            await fetchAlerts()
            await fetchProviderStatus()
            lastDevActionMessage = "Demo Trip Watch created and checked."
            refreshGeneration += 1
        } catch {
            recordRequestError("seedDemo", error)
        }
    }
    #endif

    func runEndpointTests() async -> Bool {
        lastError = nil
        let h = await fetchHealth()
        await fetchProviderStatus()
        await fetchGoals()
        await fetchAlerts()
        #if DEBUG
        return h && healthDebug.contains("| 200 |")
        #else
        return h
        #endif
    }

    #if DEBUG
    func ensureDemoDataOnLaunchIfNeeded() async {
        await fetchGoals()
        if !goals.isEmpty { return }
        let body = TripGoalCreateBody(
            origin: "San Diego",
            destination_preference: "Maui",
            budget_usd: 5000,
            start_date: "2026-06-01",
            end_date: "2026-06-10",
            needs_car: true,
            status: "active"
        )
        do {
            try await createGoal(body)
            await fetchGoals()
            if let gid = goals.first?.id {
                _ = try? await checkNow(id: gid)
            }
            await fetchGoals()
            await fetchAlerts()
            await fetchProviderStatus()
            refreshGeneration += 1
        } catch {
            recordRequestError("/trip-goals (auto-seed)", error)
        }
    }
    #endif
}
