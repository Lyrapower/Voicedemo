import SwiftUI

/// TripPack AI — design system (iOS 17+)
enum TripPack {
    static let background = Color(red: 0.965, green: 0.953, blue: 0.933)      // #F6F3EE
    static let textPrimary = Color(red: 0.063, green: 0.094, blue: 0.157)    // #101828
    static let textSecondary = Color(red: 0.4, green: 0.44, blue: 0.52)       // #667085
    static let navy = Color(red: 0.031, green: 0.184, blue: 0.286)            // #082F49
    static let ocean = Color(red: 0.055, green: 0.455, blue: 0.565)         // #0E7490
    static let passGreen = Color(red: 0.024, green: 0.463, blue: 0.278)     // #067647
    static let passTint = Color(red: 0.925, green: 0.992, blue: 0.949)     // #ECFDF3
    static let card = Color.white.opacity(0.95)
    static let shadow = Color.black.opacity(0.08)
    static let horizontalPadding: CGFloat = 18
    static let cardPadding: CGFloat = 20
    static let sectionGap: CGFloat = 22
    static let cardRadius: CGFloat = 28
    static let ctaHeight: CGFloat = 58
}

extension View {
    func tripCardShadow() -> some View {
        shadow(color: TripPack.shadow, radius: 20, x: 0, y: 10)
    }
}
