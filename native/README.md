# Native desktop migration

The platform clients share a headless JSON-lines backend (`native_bridge.py`).
The backend contains no Tk or CustomTkinter dependency. Network work happens in
the backend process and does not block a platform UI thread.

| Platform | Toolkit | Build / run |
| --- | --- | --- |
| Windows | WPF (.NET 8) | `dotnet build native/windows/Omni.csproj -c Release` |
| macOS | SwiftUI (macOS 13+) | `cd native/macos && swift build -c release` |
| Linux | GTK4 / PyGObject | `python3 native/linux/omni.py` |

Development clients use `OMNI_SOURCE_ROOT` to locate the common backend. Packaged
clients expect `Omni-Backend.exe` (Windows) or `Omni-Backend` (macOS/Linux) beside
the executable. Package the headless backend with PyInstaller; it never creates
a graphical window.

Windows renders one retained WPF visual tree. The settings button switches
existing screens inside the current window; it never changes window geometry.
The cards remain alive during percentage updates. macOS uses identity-preserving
SwiftUI views and Linux updates existing GTK controls.

These clients are migration work in progress. They are not wired into the
installer or published release. Platform builds and interaction checks, OAuth
flows, API pause behavior, native integration dialogs, translations, activity,
and updater parity must pass before replacing the shipped manager.

Windows interaction smoke test:

```
native/windows/bin/Release/net8.0-windows/Omni.exe --demo --self-test
```

The smoke test writes `native-self-test.json` after checking settings geometry,
service visibility and stable account-card identity through 100 quota updates.
It uses demo data and never touches saved accounts or the live gateway.
