import Foundation

enum RelativeTime {
    private static let iso = ISO8601DateFormatter()
    private static let isoFrac: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    static func parseISO(_ s: String) -> Date? {
        if let d = isoFrac.date(from: s) { return d }
        return iso.date(from: s)
    }

    /// Product copy for last-updated style timestamps (past).
    static func updatedPhrase(since iso: String?) -> String {
        guard let iso, let d = parseISO(iso) else { return "—" }
        let secs = max(0, Int(Date().timeIntervalSince(d)))
        if secs < 60 { return "Updated just now" }
        if secs < 3600 { return "Updated \(secs / 60)m ago" }
        return "Updated \(secs / 3600)h ago"
    }

    /// Short relative phrase for deal rows (no leading “Updated”).
    static func activityPhrase(since iso: String?) -> String {
        guard let iso, let d = parseISO(iso) else { return "—" }
        let secs = max(0, Int(Date().timeIntervalSince(d)))
        if secs < 60 { return "Just now" }
        if secs < 3600 { return "\(secs / 60)m ago" }
        return "\(secs / 3600)h ago"
    }

    /// Next scheduled check (future).
    static func nextCheckPhrase(until iso: String?) -> String? {
        guard let iso, let d = parseISO(iso), d > Date() else { return nil }
        let mins = max(1, Int(ceil(d.timeIntervalSince(Date()) / 60)))
        if mins >= 60 {
            let h = mins / 60
            return "Next check in \(h)h"
        }
        return "Next check in \(mins)m"
    }
}
