# EcoFlow Scheduler

Windows tray app for the EcoFlow DELTA Pro (original). Talks to EcoFlow's app cloud (same login as the
mobile app, unofficial) and controls the max AC charging power on a schedule.

## Run

```
pip install -r requirements.txt
python main.py            # or: python main.py --minimized
```

First start: fill in the **Settings** tab (account e-mail + password set in the EcoFlow app, device serial,
API host - `api-e.ecoflow.com` for EU). Password goes to Windows Credential Manager.
For development, `.env` (`EF_EMAIL`, `EF_PASSWORD`, `EF_SN`, `EF_API_HOST`) is used as a fallback and migrated.

**Automation starts disabled** - open the Control tab, set your rules and press *Save & apply*.

## Rules (priority high to low)

1. Temporary rule - X watts for N minutes/hours, then back to the normal rules
2. Schedule - windows with days, from/to (may cross midnight) and watts; first match wins
3. Dynamic - X1 W while battery < Y %, X2 W afterwards (2 % hysteresis)
4. Default watts

Limits: 200-2900 W. The engine compares the device limit on every update and re-sends only on mismatch.

Polling: full-state request every 3 s while the window is open and visible, every 20 s while in the tray. The unit also pushes partial updates about once a second; they are merged and coalesced (max 2 per second).

## Data

`%APPDATA%\EcoFlowScheduler\` - `settings.json`, `rules.json`, `history.db` (7 days of samples, every 30 s).

## Build exe

One step on Windows: `tools\rebuild.cmd` (or `powershell -File tools\rebuild.ps1`) runs the tests, force-closes the running app,
rebuilds `dist\EcoFlowScheduler.exe` and launches it. Options: `-NoTests`, `-NoLaunch`, `-Minimized`, `-DryRun`. A failing test
stops it before the app is touched. Manual command:

```
pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name EcoFlowScheduler --icon assets/app.ico --collect-submodules keyring.backends main.py
```

## Tests

```
python -m pytest tests          # rule logic
python tests/smoke_ui.py shots  # renders UI with fake data to PNGs
python tests/live_check.py      # read-only check against the real unit
```

Other scripts: `ef_set_ac_power.py <watts>` one-off CLI setter, `probe.py` raw message dump.

## Two devices

Run the same rules on both PCs and leave automation on in both - they do not interfere:
- Every copy compares the device's own reported limit with the rule result and sends only on a mismatch.
- Inside the dynamic-charging hysteresis band a copy keeps whatever the device is doing (no local memory), so
  copies with equal rules always agree.
- If a copy sends more than 4 commands in 10 minutes (something else keeps changing the limit - different rules on
  another PC, or the phone app) it pauses automation and shows "conflict - paused"; press *Save & apply* to resume.
- If one PC is off or has automation switched off, the other keeps controlling the unit.
- Temporary rules are local to the copy where you started them; start them on one PC only or they will be reverted.

## Battery status and power outages

- Status (charging / discharging / fully charged / on grid) comes from mains voltage (`inv.acInVol`) and the net power
  in vs out; "started HH:MM" is the beginning of the current state (seeded from local history after a restart).
- Battery bar colour: green >=70 %, yellow ~45 %, orange ~25 %, red <=10 %. The fill is animated while charging
  (light sweeps forward), discharging (slower, backwards) and fully charged (slow glow).
- Statistics > "Time without electricity": one 24 h box per day, green = grid power, blank = outage (no grid power), grey = no data
  (app off / unit offline). Hover a part for its kind, time range and power used. History rows recorded before this
  feature have no grid-power flag; they are classified by AC input power.

## Moving to another PC

Copy only `EcoFlowScheduler.exe` (self-contained, no Python needed) to a stable folder and run it.
Per-machine data lives in `%APPDATA%\EcoFlowScheduler\` and is not carried over:
- Settings tab: enter e-mail, password, serial and API host again (the password goes to that PC's Windows Credential Manager).
- Rules: a new install starts with the built-in defaults and automation OFF. To get identical rules, copy `rules.json` into
  that folder before the first start (optionally `settings.json` too - it holds everything except the password), then
  switch Automation on and press Save & apply.
- Turn "Start with Windows" on again in Settings (it points at the exe's current location).
- History (graphs, outages) is per PC and starts empty.

## Layout notes

- Dashboard: tall window = big cards stacked (battery, input | output, graph); wide window = one row of rich cells; low on space = the
  three cells collapse into one compact line so the graph always stays fully in view (scrolls only at very small sizes).
- Statistics: hover the gap between two cards to reveal a grip, press and drag to resize them (works like a window manager).
- Input graph: where data is missing, a drop of the input to ~0 W is drawn as an immediate drop (an outage), and the outage
  chart treats such a gap as an outage.

## macOS

The code is cross-platform: data lives in `~/Library/Application Support/EcoFlowScheduler`, the password in the Keychain,
"Start at login" writes a LaunchAgent (`~/Library/LaunchAgents/com.ecoflowscheduler.app.plist`), the tray icon is a menu-bar
icon whose menu shows the same status lines as the Windows tooltip (macOS has no menu-bar tooltips), and Cmd+Q quits
(the window's close button still only hides it). It runs as a menu-bar app without a Dock icon (`LSUIElement`).

Build (needs a Mac; PyInstaller cannot cross-compile):

```
pip install -r requirements.txt pyinstaller
python packaging/make_icns.py
pyinstaller --noconfirm packaging/macos.spec      # -> dist/EcoFlowScheduler.app
```

Or let GitHub build it: Actions > build > Run workflow gives `EcoFlowScheduler-macos` (Apple Silicon .app, zipped, built on the `macos-latest` runner) and the
Windows exe as artifacts; it also runs on every push to `main` and on `v*` tags. If GitHub reports an unsupported runner
configuration, the pinned image was retired - use `macos-latest`.

An unsigned app is blocked by Gatekeeper on first launch: right-click > Open, or `xattr -cr EcoFlowScheduler.app`.
For a clean install sign with a Developer ID certificate and notarize (`codesign --deep --options runtime ...`,
`xcrun notarytool submit ...`; requires an Apple Developer account).

`ECOFLOW_DATA_DIR` overrides the data folder on any platform.

## Syncing history between devices

Settings > Sync between devices shares the recorded power history with your other install(s). It is read-only and
automatic: both installs listen to the same unit, so nothing can conflict. Where one has a gap the other fills it, and where
neither recorded anything the graphs show "no data" (dashed / grey, then estimated by the outage logic). Only power numbers
are shared - never credentials or settings. Pick the **same store on every device**:

| | Shared folder | Private GitHub repository |
|---|---|---|
| Store | any folder synced by OneDrive, Dropbox, Syncthing, a NAS share ... | a private repo, through GitHub's REST Contents API (HTTPS + token, git is not needed) |
| Files | `<folder>/ecoflow-history/<serial>/<machine id>/<UTC day>.jsonl` | `ecoflow-history/<serial>/<machine id>/<UTC hour>.jsonl` in the repo |
| Interval | every 5 minutes and on close | every 30 minutes (one commit per sync while there is new data) and on close |

How it works: each install writes **only its own** files (replaced atomically) and reads the other installs' files into its
local history, tagged with their id (imported rows are never shared again). Files older than about 9 days are removed.

**GitHub setup**

1. On GitHub create a private repository (tick "Add a README") - not the public code repository.
2. Settings > Developer settings > Fine-grained tokens: repository access = only that repository, permission
   *Contents = Read and write*.
3. In the app choose GitHub, enter `owner/name` and the token on every device and press Connect.

The token is kept in the Windows Credential Manager / macOS Keychain, never in `settings.json` or the repository; stopping
sync deletes it. Public repositories and tokens without write access are refused at every sync. Authenticated GitHub calls
allow 5,000 requests per hour; a sync uses a handful.

Coverage report of the merged history: `python -m ecoflow_app.sync --days 7 [--sync]`.

## When the computer sleeps

While the PC is asleep the app is frozen: no data is recorded and no rules are applied (the unit keeps its last limit). On
wake it reconnects by itself (new login after about a minute without data), applies the rules for the current time and
resumes recording. The gap is filled from the other device's history when syncing is on, otherwise shown as no data.

## Expected outages (schedule)

Statistics > "Expected outages" shows the planned outages of your queue next to the real ones ("Time without electricity"). Set the
region and queue (group) in Settings > Outage schedule.

- **Source:** the distribution company's public schedule page (verified for DTEK Odesa, `dtek-oem.com.ua/ua/shutdowns`; no login
  or key). The other DTEK regional sites answer automated requests with a bot-protection page, so only Odesa is available for now.
- **Update:** every 10 minutes (about 160 KB per download), because schedules get revised during the day. The site only serves
  today and tomorrow, so the app saves every day it sees (latest published version wins) - that is what makes past days comparable.
- **Graphs:** same layouts as the real graph (calendar for 1-3 days, day columns for 7). Planned outages are drawn as **orange
  dashed outlines without fill**, possible outages dotted, days without a saved schedule grey. The real graph has a
  **Compare with schedule** checkbox that overlays the planned outages on the real ones (hover shows both).
- Half-hour accuracy: the schedule has hourly states plus "first/second 30 minutes". Day keys are Kyiv midnights.

## Shared settings and schedule
Syncing (folder or GitHub) also carries each install's `settings.json` and `schedule.json`:
- charging rules, temporary rule, automation on/off and the outage region/group. **The newest change wins** per item;
  the Control tab shows which device it came from. On the first run the install that saved its rules most recently wins.
- the fetched outage schedule, so a device whose own fetch is blocked still gets it from another one.

No passwords or tokens are ever written to the store. A change is synced a few seconds after you make it; other
devices pick it up at their next sync (5 minutes for a folder, 30 minutes for GitHub).

### When DTEK blocks the automatic fetch
Settings > Outage schedule can take the schedule from your own browser (the app listens on `127.0.0.1:47321` only):
- **Automatic:** install Violentmonkey or Tampermonkey, press **Install auto-send script** once. From then on every
  visit of the DTEK page sends the schedule to the running app. (Chrome: Tampermonkey also needs *Allow user scripts*.)
- **Bookmark:** **Copy bookmark code & open page**, save the code as a bookmark's address, click it on that page.
  If the browser blocks sending, the schedule is copied instead - use **Paste from clipboard**.

The app does not reload the page or pass the site's security check for you.

## Android widget
`android/` is a small Java app with one resizable home-screen widget (about 4x4 cells):
- top line: battery, state and **Input / Charging / Output / Limit** (as on the desktop's input card)
- **1d** today as a vertical timeline with planned outages as dashed outlines; **3d** the same, one day at a time,
  moving with the side arrows (Android keeps sideways swipes for home-screen pages); **7d** one row per day with
  the planned outages under it (plus tomorrow once published).

- **Get the APK:** GitHub > Actions > *android* > latest run > artifact `EcoFlowWidget-<run number>.apk` (a plain APK, no unzipping). Open it on the
  phone (allow installing from that source). Android 8 or newer.
- **The app** (also opened by tapping the widget): *Dashboard* (live battery, charging, output, energy graph),
  *Statistics* (real and planned outages, power and battery graphs - tap or drag on a graph for details) and
  *Settings*. It only monitors; rules are changed on a computer. While open it reads the unit every few seconds.
- **Set up:** in *Settings* connect the EcoFlow account (with the serial number), then the data repository with a
  fine-grained token for it (**Contents: Read-only**). Each connection is checked before it is saved. Then add the
  widget. Secrets are encrypted with the Android keystore.
- The screens are a bundled page (`android/app/src/main/assets/app`) drawn from `Model.java`'s data; it loads
  nothing from the network.
- **Freshness:** every 15 minutes at best (Android may delay it; exclude the app from battery optimisation if it
  lags). Live values come straight from EcoFlow; history and schedule from the repository (the PC syncs every 30 min).
  The phone's own readings stay on the phone and cover times when no PC was recording.
- **Updating without reinstalling** needs a stable signing key, otherwise each build has a new one and Android
  requires uninstalling first. Create it once and keep the file private:
  `keytool -genkeypair -keystore release.jks -alias ecoflow -keyalg RSA -keysize 2048 -validity 10000`
  then add two repository secrets: `ANDROID_KEYSTORE_B64` (the file, base64) and `ANDROID_KEYSTORE_PASSWORD`.
- The timeline logic is a port of `power.py`; after changing it, update `Segments.java` and run
  `python tools/make_android_golden.py`.
