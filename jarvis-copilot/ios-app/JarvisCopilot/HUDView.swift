import SwiftUI

struct HUDView: View {
    let transcript: [TranscriptItem]
    let suggestions: [Suggestion]

    @State private var isExpanded = true

    var body: some View {
        VStack {
            Spacer()

            if isExpanded {
                VStack(alignment: .leading, spacing: 10) {
                    // Recent transcript
                    ForEach(transcript.suffix(3)) { item in
                        HStack {
                            Text(item.speaker == "user" ? "You:" : "Investor:")
                                .font(.caption)
                                .foregroundColor(.gray)
                            Text(item.text)
                                .font(.caption)
                        }
                    }

                    Divider()

                    // Latest suggestion
                    if let latest = suggestions.last {
                        VStack(alignment: .leading, spacing: 5) {
                            HStack {
                                Image(systemName: "lightbulb.fill")
                                    .foregroundColor(.yellow)
                                Text("AI Suggestion:")
                                    .font(.caption)
                                    .bold()
                            }

                            Text(latest.text)
                                .font(.body)
                                .bold()
                                .foregroundColor(.white)

                            Text("Confidence: \(Int(latest.confidence * 100))%")
                                .font(.caption2)
                                .foregroundColor(.gray)
                        }
                        .padding()
                        .background(
                            RoundedRectangle(cornerRadius: 10)
                                .fill(Color.black.opacity(0.8))
                        )
                    }
                }
                .padding()
                .background(
                    RoundedRectangle(cornerRadius: 15)
                        .fill(Color.black.opacity(0.7))
                )
                .padding()
            }

            Button(action: { isExpanded.toggle() }) {
                Image(systemName: isExpanded ? "chevron.down" : "chevron.up")
                    .padding()
                    .background(Circle().fill(Color.black.opacity(0.7)))
                    .foregroundColor(.white)
            }
            .padding(.bottom)
        }
    }
}

