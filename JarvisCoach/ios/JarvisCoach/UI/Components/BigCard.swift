import SwiftUI

struct BigCard<Content: View>: View {
    let title: String
    let subtitle: String?
    let systemImage: String
    let action: () -> Void
    let content: Content

    init(
        title: String,
        subtitle: String? = nil,
        systemImage: String,
        action: @escaping () -> Void,
        @ViewBuilder content: () -> Content = { EmptyView() }
    ) {
        self.title = title
        self.subtitle = subtitle
        self.systemImage = systemImage
        self.action = action
        self.content = content()
    }

    var body: some View {
        Button(action: action) {
            HStack(alignment: .center, spacing: 16) {
                Image(systemName: systemImage)
                    .font(.system(size: 28, weight: .semibold))
                    .frame(width: 44, height: 44)
                    .background(Color.accentColor.opacity(0.15))
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.headline)
                    if let subtitle = subtitle {
                        Text(subtitle)
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                    }
                    content
                }

                Spacer()
            }
            .padding()
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(Color(.secondarySystemBackground))
            )
        }
        .buttonStyle(.plain)
    }
}

