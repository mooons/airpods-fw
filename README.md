# airpods-fw

A small macOS CLI for checking AirPods firmware, inspecting Apple's firmware
catalogs, and asking Apple's existing accessory updater to scan. The system
interfaces and catalog URLs were checked on macOS 27.0 (26A428).

Requires [uv](https://docs.astral.sh/uv/) and macOS for Bluetooth, updates and logs.
The executable uses uv to select Python 3.9 or newer, downloading an interpreter
if needed. Its inline script metadata declares no dependencies; it uses only
Python's standard library and built-in macOS commands. No pip packages or sudo.

Run with uv explicitly, or execute the script directly using its uv shebang:

```sh
uv run --script ./airpods-fw check
./airpods-fw check
```

```sh
./airpods-fw                       # offline status; default does not request updates
./airpods-fw check                 # installed vs live Apple listings
./airpods-fw update --dry-run      # inspect the action without posting a notification
./airpods-fw update                # post one system-wide scan notification
./airpods-fw logs --last 30m       # recent updater messages
./airpods-fw assets --model A3064  # live AirPods Pro 3 catalog metadata
```

To put the standalone executable on your PATH:

```sh
mkdir -p "$HOME/.local/bin"
install -m 755 airpods-fw "$HOME/.local/bin/airpods-fw"
export PATH="$HOME/.local/bin:$PATH"
```

Keep that directory on your shell's PATH, or invoke the repository executable
directly. `uv --version` checks the uv prerequisite. You can also bypass uv with
`python3 airpods-fw` if you already manage a compatible Python interpreter.

## Commands

| Command | Behavior |
| --- | --- |
| `status` | Read `system_profiler SPBluetoothDataType -json`. Show connection state, model, installed/case firmware and any reported batteries. Disconnected entries are cached observations. |
| `check` | Fetch Apple's current support-page versions and verified MobileAsset catalogs. Report them separately with their sources. |
| `update` | Verify the local launchd notification registration, then post `com.apple.SoftwareUpdate.ScanTriggered` once with `notifyutil`. |
| `logs` | Stream raw unified logs from `uarpassetmanagerd`, `uarpd`, `accessoryupdaterd` and `UARPUpdaterServiceLegacyAudio`. |
| `assets` | Read remote catalog metadata, or inspect cached catalogs and downloaded payload metadata using `--local`. No firmware files are downloaded or modified. |

`status`, `check` and `update` accept `--device` with a name, displayed device ID,
model substring or Bluetooth product ID. Exact names take precedence over
substring matches. A filter can match multiple devices. Device IDs are hashes
of local identifiers; serial numbers and Bluetooth addresses are omitted from
these commands' output. Unknown product IDs are shown when the device name
contains “AirPods,” but receive no guessed model/version association.

```sh
./airpods-fw status --json
./airpods-fw check --device 'AirPods Pro 3' --json
./airpods-fw update --device 'AirPods Pro 3' --watch 1800 --interval 30
./airpods-fw logs --duration 60
./airpods-fw logs --last 1h --debug --json
./airpods-fw assets --local --model A3064 --json
```

The update notification is **system-wide**. `--device` filters what this tool
displays/watches; Apple's scan can include other accessories. A zero exit from
`update` means the notification was posted, not that Apple accepted an update.
Running the command again posts another scan request.

`--watch SECONDS` polls installed versions. It only confirms an increase when
the same device is reported connected with a recognized, higher firmware
version. Disappearance, logs, placeholder values and case-version changes do
not count as success. If multiple devices are selected, all must show an
increase before observation exits successfully. A device already up to date
will normally time out; use `check` first. Reconnect after the waiting period
to refresh macOS's observation. Ctrl-C stops this tool; Apple's updater can
continue independently. The watcher does not stream logs; use `logs` in another
terminal for that view.

JSON is supported for `status`, `check`, `assets` and `logs`. The first three
emit one JSON object; `logs` uses Apple's native JSON format. Errors go to
stderr, with an error or warnings also in the structured result. Partial
network failure preserves installed firmware and any successfully fetched data.

Exit codes: `0` completed the requested inspection/scan (or confirmed all watched
version increases), `1` an operation/source failed, `2` invalid arguments,
`3` observation ended without confirming every selected device, `130` interrupted.
`check` returns `0` even when it finds a newer version; inspect its JSON status.

## Preparing an update

Follow [Apple's instructions](https://support.apple.com/en-us/106340): use an
updated Mac with Bluetooth enabled and Wi-Fi connected, and connect the AirPods
first. Put both earbuds in their charging case, connect the case to power,
close the lid, and keep it within Bluetooth range for at least 30 minutes.
For AirPods Max, connect the headphones to power and keep them nearby.

This utility cannot verify the lid, charging conditions, enrollment or Apple's
installation eligibility. It delegates transfer, signing, staging, activation
and recovery to macOS. It cannot force flashing, select a firmware image, bypass
eligibility or enroll/unenroll a device in beta firmware.

## Evidence and limits

- The Mac's `/System/Library/LaunchDaemons/com.apple.uarpassetmanagerd.plist`
  explicitly registers `com.apple.SoftwareUpdate.ScanTriggered` and publishes
  `com.apple.uarp.assetavailability`. `update` checks that registration at runtime
  because this is an undocumented interface that can change with macOS.
- The exact macOS catalog URL pattern came from `DownloadedFromXml` in the
  local MobileAsset metadata, then was fetched successfully:
  `https://mesu.apple.com/assets/macos/com_apple_MobileAsset_UARP_A3064/com_apple_MobileAsset_UARP_A3064.xml`.
- During validation on September 14, 2026,
  [Apple's support page](https://support.apple.com/en-us/106340) initially returned
  `8B41` for AirPods Pro 3; later fetches listed `9A348`, matching the live catalog.
  These are dated observations, not hardcoded latest versions. Catalog presence
  alone does not prove public/beta channel or eligibility. Support-page and
  cached information may lag. Local assets never determine “latest public.”
- All known models have verified catalog associations; see the table below.
  Newer models use `com.apple.MobileAsset.UARP.<model>`. Older models use
  `com.apple.MobileAsset.MobileAccessoryUpdate.<model>.EA`; placing their IDs
  under the UARP URL returns HTTP errors. Both feed formats are supported by
  `check`, `assets`, and `assets --local`. HTTP errors are reported rather than
  interpreted as “no update.” Local inspection also finds case families such as
  `A2968` and `A3122` without treating them as earbud models.
- Product-ID mappings were checked against
  [AirBattery](https://github.com/lihaoyun6/AirBattery/blob/main/AirBattery/Supports/Supports.swift)
  and local Bluetooth observations (including Pro 3 `0x2027`). Model labels and
  case distinctions follow [Apple's identification page](https://support.apple.com/en-us/109525).
  AirPods 1–5, Pro 1–3, both Max 1 connectors and Max 2 have known mappings.
  Max 2's product ID `0x202D` is present in macOS's
  `/System/Library/PrivateFrameworks/CoreBluetoothUI.framework/Versions/A/Resources/AssetPaths-B515d.plist`
  and corroborated by [LibrePods' Max 2 support change](https://github.com/librepods-org/librepods/pull/519).
  Its `A3454` catalog was fetched successfully; Max 2 hardware has not been tested.
  Unknown models are not guessed from user-editable names.
- AirPods 5 mappings were verified on September 19, 2026. Apple's identification
  page lists `A3531/A3532/A3533` for AirPods 5 and `A3439/A3440/A3441` for the
  Wireless Charging Case variant. The live `A3532` and `A3440` catalogs and
  Apple's support page all reported `9A350`. The catalogs' firmware ZIPs contain
  `AssetData/Firmware.acsw/Restore.plist`, identifying boards `b868eap` and
  `b868map`, respectively. These match macOS's
  `/System/Library/PrivateFrameworks/CoreBluetoothUI.framework/Versions/A/Resources/AssetPaths-B868.plist`:
  `B868e` uses product IDs `0x2036/0x2037`; `B868m` uses `0x2030/0x2032`.
  Identification and live source lookup were tested with synthetic device data;
  AirPods 5 hardware and installation have not been tested.
- Firmware comparisons normalize invisible formatting characters, compare
  numeric build components, and recognize `8.1.41` as `8B41`. Placeholder
  `255.15.15`, missing values and beta suffixes have unknown ordering. The
  catalog's `Build` is used instead of assuming its numeric fields encode a
  conventional version; the live Pro 3 catalog had nonstandard numeric fields.
  First-generation AirPods are the verified exception: their catalog omits
  `Build` and supplies `6`, `8`, `8` as the major/minor/release fields (`6.8.8`).
- Logs cover all matching accessory processes, may contain device identifiers,
  and may be empty or privacy-redacted. They are intentionally not converted
  into guessed percentages or claims of successful installation.

### Verified catalogs

Fetched and validated against Apple on September 19, 2026. Feed names identify
the catalog, which can differ from the printed model number (notably `A2618`
for AirPods Pro 2 with Lightning). No latest versions are hardcoded.

| Model | Catalog ID | Feed |
| --- | --- | --- |
| AirPods 1 | `A1523` | MobileAccessoryUpdate EA |
| AirPods 2 | `A2032` | MobileAccessoryUpdate EA |
| AirPods 3 | `A2564` | MobileAccessoryUpdate EA |
| AirPods 4 | `A3053` | UARP |
| AirPods 4 with ANC | `A3056` | UARP |
| AirPods 5 | `A3532` | UARP |
| AirPods 5 with Wireless Charging Case | `A3440` | UARP |
| AirPods Pro 1 | `A2084` | MobileAccessoryUpdate EA |
| AirPods Pro 2 (Lightning) | `A2618` | UARP |
| AirPods Pro 2 (USB-C) | `A3048` | UARP |
| AirPods Pro 3 | `A3064` | UARP |
| AirPods Max 1 (Lightning) | `A2096` | MobileAccessoryUpdate EA |
| AirPods Max 1 (USB-C) | `A3184` | MobileAccessoryUpdate EA |
| AirPods Max 2 | `A3454` | UARP |

All use Apple's `/assets/macos/` catalog path except first-generation AirPods,
whose working feed is under `/assets/`. Example legacy catalog:
[AirPods 2](https://mesu.apple.com/assets/macos/com_apple_MobileAsset_MobileAccessoryUpdate_A2032_EA/com_apple_MobileAsset_MobileAccessoryUpdate_A2032_EA.xml).
[The Apple Wiki's asset index](https://theapplewiki.com/wiki/List_of_Asset_Types)
provided the legacy feed names, subsequently verified against Apple's live
catalogs. The `A2618` payload's `Restore.plist` also confirms `AirPods3,1` / board
`b698ap`. Catalog access and local metadata inspection do not establish that a
firmware installation works on every listed model.

## Verification

```sh
python3 -m unittest -v test_airpods_fw.py
./airpods-fw status
./airpods-fw check --device 'AirPods Pro 3'
./airpods-fw assets --model A3064
./airpods-fw assets --local --model A3064
./airpods-fw update --device 'AirPods Pro 3' --dry-run
./airpods-fw logs --duration 1
```

Offline tests cover real profiler/version edge cases, source separation,
malformed/missing data, network failure, notification arguments, dry-run
behavior, local cache inspection and conservative update observation. They
mock hardware update actions. Live validation exercises reading, network
catalogs, logs and dry-run preparation; actual firmware installation has not
been performed or verified by this project.

## Acknowledgments

Developed with help from Codex (GPT-6).
