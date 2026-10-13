from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

import voicepack
from installer.cloud import DreameCloud, FIRMWARE, MODEL, InstallerError, PROPERTIES
from installer.operations import (
    backup, install_once, lan_address, pending_path, preflight,
    recovery_data, serve_package, verify_package,
)


DEVICE = {"did": "test-device", "model": MODEL, "fw_ver": FIRMWARE,
          "online": True, "bindDomain": "test.example.invalid:8883"}
DATA = b"test archive"
PACKAGE = {"size": len(DATA), "md5": hashlib.md5(DATA).hexdigest(),
           "sha256": hashlib.sha256(DATA).hexdigest(), "url": "https://example.invalid/stock"}


def state(phase="success", progress=100):
    return {"language": "RU", "voice_test": 0, "state": 13, "error": 0,
            "battery": 100, "charging": 1, "task": 0,
            "voice": {"id": "RU", "state": phase, "progress": progress}}


class CloudTests(unittest.TestCase):
    def test_route_with_port_and_escaped_voice_status(self):
        client = DreameCloud()
        values = state()
        values["voice"] = json.dumps(values["voice"]).replace('"', '\\\\\\"')
        rows = [{"siid": s, "piid": p, "code": 0, "value": values[name]}
                for name, (s, p) in PROPERTIES.items()]
        client.request = Mock(return_value={"result": rows})
        self.assertEqual(client.snapshot(DEVICE), state())
        self.assertEqual(client.request.call_args.args[0], "dreame-iot-com-test/device/sendCommand")

    def test_missing_property_is_rejected(self):
        client = DreameCloud()
        client.send = Mock(return_value=[])
        with self.assertRaisesRegex(InstallerError, "invalid_response"):
            client.snapshot(DEVICE)

    def test_install_is_not_retried_after_empty_response(self):
        client = DreameCloud()
        client.request = Mock(return_value=None)
        with self.assertRaisesRegex(InstallerError, "invalid_response"):
            client.install(DEVICE, PACKAGE, "http://example.invalid/pack")
        self.assertEqual(client.request.call_count, 1)

    def test_read_can_retry_once_with_new_request_id(self):
        client = DreameCloud()
        client.request = Mock(side_effect=[None, {"result": []}])
        self.assertEqual(client.send(DEVICE, "get_properties", []), [])
        calls = client.request.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0].args[1]["id"], calls[1].args[1]["id"])

    def test_wrong_property_ack_is_not_accepted(self):
        client = DreameCloud()
        client.send = Mock(return_value=[{"siid": 7, "piid": 1, "code": 0}])
        with self.assertRaisesRegex(InstallerError, "invalid_response"):
            client.install(DEVICE, PACKAGE, "http://example.invalid/pack")

    def test_does_not_store_password_or_refresh_token(self):
        client = DreameCloud()
        client.request = Mock(return_value={"access_token": "test-session", "refresh_token": "test-refresh"})
        client.login("example", "test-password")
        self.assertFalse(hasattr(client, "password"))
        self.assertFalse(hasattr(client, "refresh_token"))
        client.close()
        self.assertIsNone(client.token)


class PreflightTests(unittest.TestCase):
    def test_supported_idle_device(self):
        preflight(DEVICE, state())

    def test_model_firmware_and_online_state(self):
        for field, value in (("model", "dreame.vacuum.r2469a"), ("fw_ver", "unknown"), ("online", False)):
            with self.subTest(field=field), self.assertRaises(InstallerError):
                preflight({**DEVICE, field: value}, state())

    def test_not_ready_states(self):
        for field, value in (("battery", 49), ("error", 68), ("state", 1),
                             ("task", 1), ("charging", 5), ("voice_test", 1)):
            with self.subTest(field=field), self.assertRaisesRegex(InstallerError, "not_ready"):
                preflight(DEVICE, {**state(), field: value})
        with self.assertRaises(InstallerError):
            preflight(DEVICE, state("downloading", 20))


class BackupTests(unittest.TestCase):
    def test_backup_is_explicitly_not_an_extraction_and_contains_no_account(self):
        with tempfile.TemporaryDirectory() as directory, patch("installer.operations.download_stock", return_value=DATA):
            root = Path(directory)
            device = {**DEVICE, "password": "test-password", "token": "test-session"}
            folder = backup(root, device, state(), PACKAGE)
            record = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
            self.assertFalse(record["installed_audio_extracted"])
            self.assertEqual(record["kind"], "stock_recovery_kit")
            self.assertEqual(recovery_data(root, DEVICE, PACKAGE), DATA)
            serialized = json.dumps(record)
            for value in ("test-password", "test-session", "test-device", "did", "token", "password"):
                self.assertNotIn(value, serialized)
            with self.assertRaisesRegex(InstallerError, "backup_missing"):
                recovery_data(root, {**DEVICE, "did": "other-device"}, PACKAGE)
            (folder / "stock-ru.tar.gz").write_bytes(b"damaged")
            with self.assertRaisesRegex(InstallerError, "package_changed"):
                recovery_data(root, DEVICE, PACKAGE)

    def test_changed_archive_is_rejected(self):
        with self.assertRaisesRegex(InstallerError, "package_changed"):
            verify_package(DATA + b"!", PACKAGE)


class LocalServerTests(unittest.TestCase):
    def test_only_selected_bytes_are_exposed(self):
        opener = build_opener(ProxyHandler({}))
        with serve_package(DATA, "127.0.0.1", allow_loopback=True) as (url, downloaded):
            with opener.open(Request(url, method="HEAD")) as response:
                self.assertEqual(int(response.headers["Content-Length"]), len(DATA))
            self.assertFalse(downloaded.is_set())
            with opener.open(url) as response:
                self.assertEqual(response.read(), DATA)
            self.assertTrue(downloaded.wait(1))
            origin = url.split("/", 3)[:3]
            for path in ("/", "/.env", "/../voicepack.py"):
                with self.assertRaises(HTTPError) as caught:
                    opener.open("/".join(origin) + path)
                self.assertEqual(caught.exception.code, 404)
                caught.exception.close()

    def test_public_or_wildcard_bind_is_rejected(self):
        for address in ("0.0.0.0", "127.0.0.1", "8.8.8.8", "::1", "bad"):
            with self.subTest(address=address), self.assertRaises(InstallerError):
                lan_address(address)


class InstallationTests(unittest.TestCase):
    def run_install(self, states, side_effect=None, fetched=True):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        pending = pending_path(Path(temporary.name), DEVICE)
        client = Mock()
        client.snapshot.side_effect = states
        client.install.side_effect = side_effect
        downloaded = threading.Event()
        if fetched:
            downloaded.set()
        return client, pending, downloaded

    @patch("installer.operations.time.sleep")
    def test_new_progress_then_success(self, sleep):
        client, pending, downloaded = self.run_install([state(), state("downloading", 25), state()])
        install_once(client, DEVICE, PACKAGE, "http://example.invalid/pack", downloaded, pending, Mock())
        self.assertEqual(client.install.call_count, 1)
        self.assertFalse(pending.exists())

    @patch("installer.operations.time.sleep")
    def test_timeout_does_not_resend_and_can_still_observe_success(self, sleep):
        client, pending, downloaded = self.run_install(
            [state(), state("downloading", 25), state()], InstallerError("network_failed"))
        install_once(client, DEVICE, PACKAGE, "http://example.invalid/pack", downloaded, pending, Mock())
        self.assertEqual(client.install.call_count, 1)
        self.assertFalse(pending.exists())

    @patch("installer.operations.time.sleep")
    def test_stale_success_is_unknown_and_lock_survives(self, sleep):
        client, pending, downloaded = self.run_install([])
        client.snapshot.side_effect = None
        client.snapshot.return_value = state()
        with patch("installer.operations.time.monotonic", side_effect=[0, 0, 1]):
            with self.assertRaisesRegex(InstallerError, "outcome_unknown"):
                install_once(client, DEVICE, PACKAGE, "http://example.invalid/pack", downloaded, pending, Mock(), timeout=1)
        self.assertTrue(pending.exists())
        with self.assertRaisesRegex(InstallerError, "pending_exists"):
            install_once(client, DEVICE, PACKAGE, "http://example.invalid/pack", downloaded, pending, Mock())
        self.assertEqual(client.install.call_count, 1)

    @patch("installer.operations.time.sleep")
    def test_missing_download_is_not_success(self, sleep):
        client, pending, downloaded = self.run_install([state(), state("downloading", 25), state()], fetched=False)
        with patch("installer.operations.time.monotonic", side_effect=[0, 0, 0, 1]):
            with self.assertRaisesRegex(InstallerError, "outcome_unknown"):
                install_once(client, DEVICE, PACKAGE, "http://example.invalid/pack", downloaded, pending, Mock(), timeout=1)
        self.assertTrue(pending.exists())

    def test_rejection_sends_once_and_clears_pending(self):
        client, pending, downloaded = self.run_install([state()], InstallerError("command_rejected"))
        with self.assertRaisesRegex(InstallerError, "command_rejected"):
            install_once(client, DEVICE, PACKAGE, "http://example.invalid/pack", downloaded, pending, Mock())
        self.assertEqual(client.install.call_count, 1)
        self.assertFalse(pending.exists())


class WorkflowTests(unittest.TestCase):
    @patch("installer.operations.time.sleep")
    def test_install_and_restore_workflows(self, sleep):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "voicepack").mkdir()
            (root / "voicepack/test.tar.gz").write_bytes(DATA)
            manifest = {"package": {**PACKAGE, "file": "test.tar.gz"}, "stock_restore": PACKAGE}
            client = Mock()
            client.info.return_value = DEVICE
            client.snapshot.side_effect = [state(), state(), state("downloading", 25), state()]
            completed = None

            def download(device, package, url):
                with build_opener(ProxyHandler({})).open(url) as response:
                    self.assertEqual(response.read(), DATA)
                self.assertTrue(completed.wait(timeout=5), "Server did not confirm the download")

            client.install.side_effect = download

            @contextmanager
            def serve(data, address):
                nonlocal completed
                with serve_package(data, address, allow_loopback=True) as (url, completed):
                    yield url, completed

            with (patch.object(voicepack, "ROOT", root),
                  patch.object(voicepack, "LOCAL", root / ".my_local_dev"),
                  patch.object(voicepack, "validate"), patch.object(voicepack, "say"),
                  patch.object(voicepack, "ask", return_value="127.0.0.1"),
                  patch.object(voicepack, "confirm", side_effect=[True, False, True, False]),
                  patch.object(voicepack, "serve_package", side_effect=serve),
                  patch("installer.operations.download_stock", return_value=DATA)):
                voicepack.execute("install", client, DEVICE, manifest)
                self.assertEqual(len(list((root / ".my_local_dev/backups").glob("*/snapshot.json"))), 1)
                client.snapshot.side_effect = [state(), state(), state("downloading", 25), state()]
                voicepack.execute("restore", client, DEVICE, manifest)
            self.assertEqual(client.install.call_count, 2)
            self.assertFalse(pending_path(root / ".my_local_dev", DEVICE).exists())


if __name__ == "__main__":
    unittest.main()
