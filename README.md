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

Or let GitHub build it: Actions > build > Run workflow gives `EcoFlowScheduler-macos` (Apple Silicon .app, zipped) and the
Windows exe as artifacts (tags `v*` also trigger it).

An unsigned app is blocked by Gatekeeper on first launch: right-click > Open, or `xattr -cr EcoFlowScheduler.app`.
For a clean install sign with a Developer ID certificate and notarize (`codesign --deep --options runtime ...`,
`xcrun notarytool submit ...`; requires an Apple Developer account).

`ECOFLOW_DATA_DIR` overrides the data folder on any platform.
