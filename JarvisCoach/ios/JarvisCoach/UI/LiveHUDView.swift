import SwiftUI

struct LiveHUDView: View {
    @EnvironmentObject var session: SessionViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var debugExpanded = false

    var body: some View {
        ZStack {
            Color.black.opacity(0.96)
                .ignoresSafeArea()

            VStack {
                topBar
                    .padding(.horizontal, 16)
                    .padding(.top, 12)

                Spacer()

                suggestionArea

                Spacer()

                bottomControls
                    .padding(.bottom, 24)
                    .padding(.horizontal, 20)
            }

            VStack {
                HStack {
                    Spacer()
                    DebugFold(
                        isExpanded: $debugExpanded,
                        lastUtterance: session.lastUtterance,
                        lastUpdated: session.suggestion.lastUpdated,
                        lastLatency: session.suggestion.lastLatency,
                        clearAction: { session.clearDebug() }
                    )
                    .padding(.top, 8)
                    .padding(.trailing, 12)
                }
                Spacer()
            }
        }
        .onDisappear {
            session.stopSession()
        }
        .toolbar {
            ToolbarItem(placement: .navigationBarLeading) {
                Button("Back") {
                    dismiss()
                }
                .foregroundColor(.white)
            }
        }
    }

    private var topBar: some View {
        HStack(spacing: 12) {
            Text("Mode: \(session.mode.displayName)")
            Text("Lang: \(session.language.displayName)")
            Text("Speaker: \(session.speakerRole.displayName)")

            Spacer()

            switch session.claudeState {
            case .idle:
                Text("Claude: idle")
            case .ok:
                Text("Claude: OK")
                    .foregroundColor(.green)
            case .unavailable(let msg):
                Text("Claude: error")
                    .foregroundColor(.orange)
                    .overlay(
                        Text(msg)
                            .font(.caption2)
                            .foregroundColor(.orange)
                            .padding(.top, 16),
                        alignment: .bottom
                    )
            }
        }
        .font(.footnote)
        .foregroundColor(.white.opacity(0.8))
    }

    private var suggestionArea: some View {
        VStack(spacing: 16) {
            if session.suggestion.text.isEmpty {
                Text("等待对方说话中…")
                    .font(.system(size: 36, weight: .semibold, design: .rounded))
                    .foregroundColor(.white.opacity(0.4))
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 24)
            } else {
                Text(session.suggestion.text)
                    .font(.system(size: 40, weight: .bold, design: .rounded))
                    .foregroundColor(.white)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
                    .minimumScaleFactor(0.6)
                    .padding(.horizontal, 24)
                    .id(session.suggestion.text)
                    .transition(.opacity.combined(with: .scale(scale: 0.98)))
            }

            if session.suggestion.isLoading {
                ProgressView()
                    .tint(.white)
            }
        }
    }

    private var bottomControls: some View {
        VStack(spacing: 16) {
            HStack {
                Picker("Speaker", selection: $session.speakerRole) {
                    ForEach(SpeakerRole.allCases) { role in
                        Text(role.displayName).tag(role)
                    }
                }
                .pickerStyle(.segmented)
            }

            HStack(spacing: 12) {
                Button {
                    session.togglePause()
                } label: {
                    labelFor(
                        text: session.isPaused ? "Resume" : "Pause",
                        systemImage: session.isPaused ? "play.fill" : "pause.fill"
                    )
                }

                Button {
                    session.applyShorter()
                } label: {
                    labelFor(text: "Shorter", systemImage: "text.line.first.and.arrowtriangle.forward")
                }

                Button {
                    session.applyMoreDirect()
                } label: {
                    labelFor(text: "More direct", systemImage: "bolt.fill")
                }

                Button(role: .destructive) {
                    session.resetContext()
                } label: {
                    labelFor(text: "Reset", systemImage: "arrow.counterclockwise")
                }
            }
        }
    }

    private func labelFor(text: String, systemImage: String) -> some View {
        VStack {
            Image(systemName: systemImage)
                .font(.system(size: 18, weight: .semibold))
            Text(text)
                .font(.caption2)
        }
        .foregroundColor(.white)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 10)
        .background(Color.white.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

