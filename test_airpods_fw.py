"""Offline regression checks: python3 -m unittest -v test_airpods_fw.py"""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).with_name("airpods-fw")
loader = importlib.machinery.SourceFileLoader("airpods_fw", str(PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
fw = importlib.util.module_from_spec(spec)
loader.exec_module(fw)


def profiler(firmware="8B40", connected=True, name="My headphones"):
    return {"SPBluetoothDataType": [{
        "device_connected" if connected else "device_not_connected": [{name: {
            "device_address": "00:11:22:33:44:55",
            "device_serialNumber": "PRIVATE-SERIAL",
            "device_vendorID": "0x004C (Apple)",
            "device_productID": "0x2027",
            "device_firmwareVersion": firmware,
            "device_batteryLevelLeft": "50%",
        }}],
    }]}


def catalog(build="9A348", model="A3064"):
    return {"AssetType": "com.apple.MobileAsset.UARP." + model, "Assets": [{
        "DeviceName": model, "Build": build,
        # Observed nonstandard numeric fields must not override the Build string.
        "FirmwareVersionMajor": 90, "FirmwareVersionMinor": 3431000025000000,
        "__BaseURL": "https://updates.cdn-apple.com/example/",
        "__RelativePath": "firmware.zip", "_DownloadSize": 12538358,
    }]}


SUPPORT_HTML = """
<script>AirPods Pro 3: 99Z999</script>
<h2 id="latest">Latest AirPods firmware versions</h2><ul>
<li><p>AirPods Pro <b>3</b>: 8B41</p></li>
<li><p>AirPods Max 1 (USB-C): 7E108</p></li>
<li><p>AirPods (1st generation): 6.8.8</p></li></ul>
<h2 id="history">Release notes</h2><p>AirPods Pro 3: 8B40</p>
"""


class AirPodsFirmwareTests(unittest.TestCase):
    def invoke(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = fw.main(list(args))
        return code, output.getvalue(), errors.getvalue()

    def test_real_profiler_edge_cases_and_identifiers(self):
        data = profiler("7\u200bE108")
        data["SPBluetoothDataType"][0]["device_not_connected"] = [
            {"Old name": profiler()["SPBluetoothDataType"][0]["device_connected"][0]["My headphones"]},
            {"Mouse": {"device_productID": "0xB037", "device_vendorID": "0x046D"}},
            {"AirPods Future": {"device_productID": "0xFFFF"}},
        ]
        devices = fw.parse_devices(data)
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0]["model"], "AirPods Pro 3")
        self.assertEqual(devices[0]["installed"], "7E108")
        self.assertTrue(devices[0]["connected"])
        self.assertIsNone(devices[1]["model"])
        self.assertNotIn("PRIVATE-SERIAL", json.dumps(devices))
        self.assertNotIn("00:11:22:33:44:55", json.dumps(devices))
        self.assertEqual(fw.select_devices(devices, devices[0]["id"]), devices[:1])
        with self.assertRaises(fw.Error):
            fw.select_devices(devices, "missing")
        with self.assertRaises(fw.Error):
            fw.parse_devices({"unexpected": []})
        multi_adapter = profiler("8B40", connected=False)
        multi_adapter["SPBluetoothDataType"] += profiler("8B41")["SPBluetoothDataType"]
        self.assertEqual(fw.parse_devices(multi_adapter)[0]["installed"], "8B41")

    def test_version_ordering_and_unusable_values(self):
        for installed, latest, expected in (
            ("8B9", "8B41", "update_available"),
            ("8B100", "8B41", "ahead"),
            ("8.1.41", "8B41", "current"),
            ("7\u200bE108", "7E108", "current"),
            ("6.8.8", "6.8.8", "current"),
            ("255.15.15", "8B41", "unknown"),
            ("8B5034f", "8B41", "unknown"),
            (None, "8B41", "unknown"),
            ("0.0.0", "8B41", "unknown"),
        ):
            with self.subTest(installed=installed, latest=latest):
                self.assertEqual(fw.compare(installed, latest), expected)

    def test_support_section_ignores_scripts_and_history(self):
        versions = fw.parse_support(SUPPORT_HTML)
        self.assertEqual(versions[fw.model_key("AirPods Pro 3")], "8B41")
        self.assertEqual(versions[fw.model_key("AirPods 1")], "6.8.8")
        self.assertEqual(fw.model_key("AirPods Max (USB-C)"), fw.model_key("AirPods Max 1 (USB-C)"))
        with self.assertRaises(fw.Error):
            fw.parse_support("<h2>Changed page</h2><p>AirPods Pro 3: 8B41</p>")

    def test_catalog_uses_build_and_validates_model(self):
        assets = fw.parse_catalog(catalog(), "A3064")
        self.assertEqual(assets[0]["build"], "9A348")
        self.assertEqual(assets[0]["url"], "https://updates.cdn-apple.com/example/firmware.zip")
        self.assertEqual(fw.catalog_url("A3064"),
                         "https://mesu.apple.com/assets/macos/com_apple_MobileAsset_UARP_A3064/com_apple_MobileAsset_UARP_A3064.xml")
        with self.assertRaises(fw.Error):
            fw.parse_catalog(catalog(model="A3122"), "A3064")
        with self.assertRaises(fw.Error):
            fw.catalog_url("../../private")
        malformed = catalog()
        malformed["Assets"][0]["_DownloadSize"] = "not a size"
        with self.assertRaises(fw.Error):
            fw.parse_catalog(malformed, "A3064")
        with patch.object(fw, "fetch", return_value=b"<?xml version='1.0'?><plist><dict>"), self.assertRaises(fw.Error):
            fw.remote_catalog("A3064")

    def test_check_keeps_public_and_catalog_separate(self):
        def fetch(url):
            return SUPPORT_HTML.encode() if url == fw.SUPPORT_URL else plistlib.dumps(catalog())
        with patch.object(fw, "read_devices", return_value=fw.parse_devices(profiler("8B41"))), patch.object(fw, "fetch", side_effect=fetch):
            code, output, _ = self.invoke("check", "--json")
        self.assertEqual(code, 0)
        device = json.loads(output)["devices"][0]
        self.assertEqual(device["public_status"], "current")
        self.assertEqual(device["catalog"]["assets"][0]["build"], "9A348")
        self.assertEqual(device["catalog"]["eligibility"], "unknown")

    def test_legacy_catalog_formats_and_first_generation_version(self):
        legacy = catalog("6F21", "A2032")
        legacy["Assets"][0]["DeviceName"] = "Bluetooth Headset"
        for asset_type in ("MobileAccessoryUpdate_A2032_EA",
                           "com.apple.MobileAsset.MobileAccessoryUpdate.A2032.EA"):
            legacy["AssetType"] = asset_type
            self.assertEqual(fw.parse_catalog(legacy, "A2032")[0]["build"], "6F21")
        self.assertIn("/assets/macos/com_apple_MobileAsset_MobileAccessoryUpdate_A2032_EA/",
                      fw.catalog_url("A2032"))
        with self.assertRaises(fw.Error):
            fw.parse_catalog(legacy, "A2084")  # Same generic DeviceName, different model.
        with self.assertRaises(fw.Error):
            fw.parse_catalog(legacy, "A3064")
        del legacy["Assets"][0]["Build"]
        self.assertIsNone(fw.parse_catalog(legacy, "A2032")[0]["build"])
        legacy["AssetType"] = "com.apple.MobileAsset.MobileAccessoryUpdate.A1523.EA"
        legacy["Assets"][0].update(DeviceName="AirPods", FirmwareVersionMajor=6,
                                    FirmwareVersionMinor=8, FirmwareVersionRelease=8)
        self.assertEqual(fw.parse_catalog(legacy, "A1523")[0]["build"], "6.8.8")
        self.assertIn("/assets/com_apple_MobileAsset_MobileAccessoryUpdate_A1523_EA/",
                      fw.catalog_url("A1523"))
        legacy["Assets"][0]["FirmwareVersionMinor"] = "8"
        with self.assertRaises(fw.Error):
            fw.parse_catalog(legacy, "A1523")
        legacy["AssetType"] = []
        with self.assertRaises(fw.Error):
            fw.parse_catalog(legacy, "A1523")

    def test_network_failure_preserves_installed_firmware_in_json(self):
        with patch.object(fw, "read_devices", return_value=fw.parse_devices(profiler())), patch.object(fw, "fetch", side_effect=fw.Error("offline")):
            code, output, errors = self.invoke("check", "--json")
        self.assertEqual(code, 1)
        data = json.loads(output)
        self.assertEqual(data["devices"][0]["installed"], "8B40")
        self.assertEqual(data["devices"][0]["public_status"], "unknown")
        self.assertIn("offline", errors)

    def test_scan_registration_and_dry_run_then_mocked_post(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launch.plist"
            path.write_bytes(plistlib.dumps({"LaunchEvents": {"com.apple.notifyd.matching": {
                "softwareupdate.scantriggered": {"Notification": fw.NOTIFICATION},
            }}}))
            with patch.object(fw, "LAUNCH_PLIST", path), patch.object(fw, "require_macos"), patch.object(fw, "read_devices", return_value=fw.parse_devices(profiler())), patch.object(fw, "run") as run:
                code, output, _ = self.invoke("update", "--dry-run", "--watch", "1800")
                self.assertEqual(code, 0)
                self.assertIn("Dry run", output)
                run.assert_not_called()
                code, output, _ = self.invoke("update")
                self.assertEqual(code, 0)
                run.assert_called_once_with(["/usr/bin/notifyutil", "-p", fw.NOTIFICATION], timeout=10)
                self.assertIn("installation are not confirmed", output)
                path.write_bytes(plistlib.dumps({"LaunchEvents": {}}))
                self.assertEqual(self.invoke("update")[0], 1)
                self.assertEqual(run.call_count, 1)

    def test_watch_requires_same_connected_device_and_firmware_increase(self):
        before = fw.parse_devices(profiler())
        for observed, expected in ((profiler("8B41"), 0),
                                   (profiler("8B41", False), 3),
                                   (profiler("255.15.15"), 3),
                                   (profiler("8B39"), 3),
                                   (profiler("8B40"), 3)):
            with self.subTest(observed=observed), patch.object(fw, "read_devices", return_value=fw.parse_devices(observed)), patch.object(fw.time, "sleep"), patch.object(fw.time, "monotonic", side_effect=[0, 0, 0, 2]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(fw.watch_versions(before, 1, 1), expected)
        another = fw.parse_devices(profiler("8B41"))
        another[0]["id"] = "different-accessory"
        with patch.object(fw, "read_devices", return_value=another), patch.object(fw.time, "sleep"), patch.object(fw.time, "monotonic", side_effect=[0, 0, 0, 2]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fw.watch_versions(before, 1, 1), 3)

    def test_local_assets_distinguish_cached_catalog_and_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "com_apple_MobileAsset_UARP_A3064"
            folder.mkdir()
            (folder / (folder.name + ".xml")).write_bytes(plistlib.dumps(catalog()))
            asset = folder / "example.asset"
            asset.mkdir()
            (asset / "Info.plist").write_bytes(plistlib.dumps({
                "MobileAssetProperties": {"Build": "8B41"}, "CFBundleShortVersionString": "8.1.41"}))
            with patch.object(fw, "ASSET_ROOT", root):
                result, warnings = fw.local_assets("A3064")
                self.assertFalse(warnings)
                self.assertEqual(result[0]["kind"], "cached_catalog")
                self.assertFalse(result[1]["assets"][0]["payload_present"])
                payload = asset / "AssetData/Firmware.acsw/firmware.uarp"
                payload.parent.mkdir(parents=True)
                payload.touch()
                self.assertTrue(fw.local_assets("A3064")[0][1]["assets"][0]["payload_present"])

                folder = root / "com_apple_MobileAsset_MobileAccessoryUpdate_A2032_EA"
                folder.mkdir()
                legacy = catalog("6F21", "A2032")
                legacy["AssetType"] = "MobileAccessoryUpdate_A2032_EA"
                legacy["Assets"][0]["DeviceName"] = "Bluetooth Headset"
                (folder / (folder.name + ".xml")).write_bytes(plistlib.dumps(legacy))
                asset = folder / "legacy.asset"
                bundle = asset / "AssetData/Firmware.acsw"
                bundle.mkdir(parents=True)
                (asset / "Info.plist").write_bytes(plistlib.dumps({
                    "MobileAssetProperties": {"Build": "6F21", "FirmwareBundle": "Firmware.acsw"}}))
                (bundle / "Info.plist").write_bytes(plistlib.dumps({"FirmwareImageFile": "ftab.bin"}))
                self.assertFalse(fw.local_assets("A2032")[0][1]["assets"][0]["payload_present"])
                (bundle / "ftab.bin").touch()
                result, warnings = fw.local_assets()
                self.assertFalse(warnings)
                self.assertEqual({r["model"] for r in result}, {"A2032", "A3064"})
                legacy_asset = next(r for r in result if r["model"] == "A2032" and r["kind"] == "local_asset")
                self.assertTrue(legacy_asset["assets"][0]["payload_present"])

    def test_logs_invokes_native_log_with_bounded_duration(self):
        with patch.object(fw, "require_macos"), patch.object(fw.subprocess, "call", return_value=0) as call:
            self.assertEqual(self.invoke("logs", "--duration", "1")[0], 0)
        command = call.call_args[0][0]
        self.assertEqual(command[:2], ["/usr/bin/log", "stream"])
        self.assertEqual(command[-2:], ["--timeout", "1"])
        self.assertIn(fw.PREDICATE, command)
        with patch.object(fw, "require_macos"), patch.object(fw.subprocess, "Popen") as popen:
            process = popen.return_value
            process.stdout = io.StringIO('Filtering the log data using "predicate"\n[]')
            process.wait.return_value = 0
            process.poll.return_value = 0
            code, output, errors = self.invoke("logs", "--duration", "1", "--json")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output), [])
            self.assertIn("Filtering the log data using", errors)

    def test_command_failure_and_no_implicit_updates(self):
        with patch.object(fw.subprocess, "run", return_value=subprocess.CompletedProcess([], 5, "", "denied")):
            with self.assertRaisesRegex(fw.Error, "denied"):
                fw.run(["example"])
        with patch.object(fw, "read_devices", return_value=[]), patch.object(fw, "scan_command") as scan:
            self.assertEqual(self.invoke()[0], 0)
            self.assertEqual(self.invoke("update")[0], 1)
            scan.assert_not_called()


if __name__ == "__main__":
    unittest.main()
