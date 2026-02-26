# RadarBrief iOS Wrapper Release

## 1) Local run (backend + iOS app)

1. Start backend first:
   ```bash
   MPLCONFIGDIR="./.mplconfig" ./.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```
2. Open:
   - `ios-wrapper/RadarBriefIOS/RadarBriefIOS.xcodeproj`
3. In Xcode:
   - Select target `RadarBriefIOS`
   - Signing & Capabilities:
     - `Automatically manage signing` = ON
     - `Team` = your Apple ID team
     - Bundle ID = `com.lyra.airadar` (or unique variant if conflict)
4. Select your iPhone device, press **Run**.
5. App opens RadarBrief at `http://127.0.0.1:8000/dashboard`.
   - If needed, tap **Settings** in app and change Base URL.

## 2) Archive and release build

1. In Xcode, set scheme to `RadarBriefIOS` and destination to **Any iOS Device (arm64)**.
2. `Product` -> `Archive`.
3. Wait for Organizer to open and show the new archive.

Archive location:
- `~/Library/Developer/Xcode/Archives/<date>/RadarBriefIOS <time>.xcarchive`

## 3) TestFlight upload

1. Organizer -> select archive -> `Distribute App`
2. Choose: `App Store Connect`
3. Choose: `Upload`
4. Keep default options (or include symbols), continue and upload.
5. In App Store Connect:
   - TestFlight -> Internal Testing
   - Add yourself and install via TestFlight app.

## 4) Minimum metadata checklist (upload)

- App Name: RadarBrief
- Bundle ID: same as Xcode target
- Version: `1.0`
- Build: increment each upload (`1`, `2`, ...)
- Privacy Policy URL (required for review readiness)
- Support URL (recommended)

## 5) Common quick fixes

- Signing error:
  - Re-select Team and unique Bundle ID in Signing & Capabilities.
- “No profiles for bundle”:
  - Keep Automatic signing ON and retry build.
- App can’t load page:
  - Ensure backend is running at `127.0.0.1:8000`
  - Update Base URL in app Settings.
