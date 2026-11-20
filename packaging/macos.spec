# PyInstaller spec for the macOS menu-bar app. Build ON A MAC from the repo root:
#   python packaging/make_icns.py && pyinstaller --noconfirm packaging/macos.spec
# Result: dist/EcoFlowScheduler.app
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["../main.py"],
    pathex=[".."],
    hiddenimports=collect_submodules("keyring.backends"),   # macOS Keychain backend
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="EcoFlowScheduler", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="EcoFlowScheduler")
app = BUNDLE(
    coll,
    name="EcoFlowScheduler.app",
    icon="../assets/app.icns",
    bundle_identifier="com.ecoflowscheduler.app",
    info_plist={
        "LSUIElement": True,                 # menu-bar app: no Dock icon (same idea as the Windows tray app)
        "NSHighResolutionCapable": True,
        "CFBundleShortVersionString": "1.0",
    },
)
