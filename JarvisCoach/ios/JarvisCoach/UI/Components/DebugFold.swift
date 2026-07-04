import SwiftUI

struct DebugFold: View {
    @Binding var isExpanded: Bool
    let lastUtterance: String
    let lastUpdated: Date?
    let lastLatency: TimeInterval?
    let clearAction: () -> Void

    var body: some View {
        VStack(alignment: .trailing, spacing: 8) {
            Button {
                withAnimation(.spring(response: 0.25, dampingFraction: 0.9)) {
                    isExpanded.toggle()
                }
            } label: {
                Label(isExpanded ? "Debug" : "Debug", systemImage: isExpanded ? "chevron.up" : "chevron.down")
                    .font(.caption)
                    .padding(8)
                    .background(Color.black.opacity(0.4))
                    .foregroundColor(.white)
                    .clipShape(Capsule())
            }

            if isExpanded {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Last utterance")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    ScrollView {
                        Text(lastUtterance.isEmpty ? "—" : lastUtterance)
                            .font(.footnote)
                            .foregroundColor(.primary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 80)

                    HStack {
                        if let lastUpdated {
                            Text("Updated: \(lastUpdated.formatted(date: .omitted, time: .standard))")
                        }
                        if let latency = lastLatency {
                            Text(String(format: "Latency: %.1fs", latency))
                        }
                    }
                    .font(.caption2)
                    .foregroundColor(.secondary)

                    HStack {
                        Spacer()
                        Button("Clear") {
                            clearAction()
                        }
                        .font(.caption)
                    }
                }
                .padding(10)
                .background(.ultraThinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
        }
    }
}

