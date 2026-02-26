# Demo Artifacts — How to Generate

This folder is for demo evidence: screen recordings (mp4), voice samples (mp3), subtitles (srt), and prompt copies. None are committed by default to avoid large binaries; generate as needed.

## Screen recording (mp4)

1. Start backend: `MPLCONFIGDIR="./.mplconfig" ./.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000`
2. Open http://127.0.0.1:8000/dashboard in Chrome or Safari.
3. Record:
   - **macOS:** QuickTime Player → File → New Screen Recording, or Cmd+Shift+5 (Screenshot/Record).
   - **iOS:** Control Center → Screen Recording.
4. Follow `docs/DEMO/DEMO_SCRIPT.md` (30–120s).
5. Save as `assets/demo/radarbrief-demo.mp4` (or similar).

## Voice brief (mp3)

- The app generates briefs on demand via **Brief** tab → Generate → Play.
- Backend writes TTS to a temp file and streams it; to keep a sample:
  1. Use browser DevTools → Network, filter by "tts" or "audio".
  2. After Play, open the request that returns audio and "Save as" → e.g. `assets/demo/brief-sample.mp3`.
- Or use a system audio capture (e.g. BlackHole + QuickTime) while playing the brief.

## Subtitles (srt)

- Create a `.srt` file with timestamps matching your mp4. Example format:
  ```
  1
  00:00:00,000 --> 00:00:05,000
  Welcome to RadarBrief. Click Start.
  ```
- Name it `assets/demo/radarbrief-demo.srt` and use in a player that supports SRT.

## Prompt / script copy

- After **Generate** on the Brief tab, copy the displayed script text into `assets/demo/brief-script-sample.txt` (optional, for reviewers).

## Voice MVP — Screen recording (mp4)

1. Start backend: `MPLCONFIGDIR="./.mplconfig" ./.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000`
2. Open http://127.0.0.1:8000/ in browser.
3. Record screen (e.g. Cmd+Shift+5 on macOS).
4. Follow Voice section in `docs/DEMO/DEMO_SCRIPT.md`: Start → Stop → Analyze → Happened/Not Happened → Find Similar Sessions → Predict; optionally open dashboard.
5. Save as `assets/demo/voice-demo.mp4`.

## Voice MVP — Optional audio

- Recordings are uploaded as WAV; no separate mp3 required unless you want a sample of “before analyze” audio. To keep one: after Record → Stop, use browser DevTools → Network, find the upload request, or export from your recording tool.

---

## Checklist before sharing

- [ ] mp4 under 2 minutes, shows Landing → Radar → Brief (Play) → Settings (RadarBrief)
- [ ] Voice: mp4 shows Record → Analyze → Outcome → Neighbors → Predict (or dashboard)
- [ ] mp3 is one full brief play (no loop) if RadarBrief
- [ ] No secrets or tokens visible in recording
