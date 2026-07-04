import SwiftUI

struct ScriptLibraryView: View {
    @EnvironmentObject var session: SessionViewModel
    @State private var localTracks: TalkTracks = TalkTracks(modes: [:])

    var body: some View {
        Form {
            ForEach(ConversationMode.allCases) { mode in
                Section(mode.displayName) {
                    let binding = Binding<[String]>(
                        get: { session.talkTracks.modes[mode.rawValue]?.bullets ?? [] },
                        set: { newValue in
                            var updated = session.talkTracks
                            updated.modes[mode.rawValue] = TalkTrackModeConfig(bullets: newValue)
                            session.saveTalkTracks(updated)
                        }
                    )

                    EditableBulletsView(bullets: binding)
                }
            }

            Section {
                Button("Reset to default") {
                    let loader = TalkTracksLoader()
                    let defaults = loader.load()
                    session.saveTalkTracks(defaults)
                }
                .foregroundColor(.red)
            }
        }
        .navigationTitle("Talk Tracks")
        .onAppear {
            localTracks = session.talkTracks
        }
    }
}

private struct EditableBulletsView: View {
    @Binding var bullets: [String]

    var body: some View {
        ForEach(bullets.indices, id: \.self) { index in
            HStack(alignment: .top) {
                Text("\(index + 1).")
                    .foregroundColor(.secondary)
                TextField("Bullet", text: Binding(
                    get: { bullets[index] },
                    set: { bullets[index] = $0 }
                ), axis: .vertical)
                .textFieldStyle(.roundedBorder)
            }
        }
        .onDelete { indexSet in
            bullets.remove(atOffsets: indexSet)
        }

        Button {
            bullets.append("")
        } label: {
            Label("Add bullet", systemImage: "plus.circle")
        }
    }
}

