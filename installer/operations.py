"""Package checks, local recovery copies and one-shot installation."""

from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import threading
import time
from urllib.error import URLError
from urllib.request import Request, build_opener

from .cloud import FIRMWARE, MODEL, InstallerError, NoRedirect


TERMINAL_STATES = {"idle", "idel", "success", "fail"}


def preflight(info, state):
    if info.get("model") != MODEL or info.get("fw_ver") != FIRMWARE:
        raise InstallerError("unsupported_device")
    if info.get("online") not in (True, 1, "1"):
        raise InstallerError("offline")
    if (type(state.get("battery")) is not int or state["battery"] < 50
            or state.get("error") != 0 or state.get("state") not in (6, 13)
            or state.get("charging") not in (1, 2, 3) or state.get("task") != 0
            or state.get("voice_test") != 0
            or state.get("voice", {}).get("state") not in TERMINAL_STATES):
        raise InstallerError("not_ready")


def verify_package(data, package):
    if (len(data) != package["size"]
            or hashlib.sha256(data).hexdigest() != package["sha256"]
            or hashlib.md5(data).hexdigest() != package["md5"]):
        raise InstallerError("package_changed")
    return data


def device_key(device):
    return hashlib.sha256(("eu:" + str(device["did"])).encode()).hexdigest()


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(data, ensure_ascii=True, indent=2) + "\n")
    path.chmod(0o600)


def download_stock(package):
    if not package["url"].startswith("https://oss.iot.dreame.life/dreame-product/resources/"):
        raise InstallerError("package_changed")
    try:
        request = Request(package["url"], headers={"User-Agent": "VoicePack/1.0"})
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            data = response.read(package["size"] + 1)
    except (URLError, TimeoutError, OSError):
        raise InstallerError("stock_download_failed") from None
    return verify_package(data, package)


def backup(root, device, state, package):
    base = root / "backups"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = download_stock(package)
    for index in range(1, 10000):
        folder = base / f"backup-{index:04}"
        try:
            folder.mkdir(mode=0o700)
            break
        except FileExistsError:
            continue
    else:
        raise InstallerError("backup_failed")
    archive = folder / "stock-ru.tar.gz"
    archive.write_bytes(data)
    archive.chmod(0o600)
    safe_state = {key: state[key] for key in (
        "language", "battery", "state", "error", "charging", "task", "voice_test",
    )}
    save_json(folder / "snapshot.json", {
        "schema_version": 1, "model": MODEL, "firmware": FIRMWARE,
        "device_key": device_key(device), "state": safe_state,
        "kind": "stock_recovery_kit", "installed_audio_extracted": False,
        "stock_sha256": package["sha256"],
    })
    return folder


def recovery_data(root, device, package):
    for folder in sorted((root / "backups").glob("backup-*"), reverse=True):
        try:
            record = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
            if (record.get("device_key") != device_key(device)
                    or record.get("model") != MODEL or record.get("firmware") != FIRMWARE):
                continue
            return verify_package((folder / "stock-ru.tar.gz").read_bytes(), package)
        except (OSError, ValueError):
            continue
    raise InstallerError("backup_missing")


def pending_path(root, device):
    return root / ("pending-" + device_key(device)[:16] + ".json")


def default_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(("192.0.2.1", 9))
            return connection.getsockname()[0]
    except OSError:
        return ""


def lan_address(address, allow_loopback=False):
    try:
        ip = ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError:
        raise InstallerError("invalid_lan_address") from None
    networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    if not any(ip in ipaddress.IPv4Network(network) for network in networks):
        if not (allow_loopback and ip.is_loopback):
            raise InstallerError("invalid_lan_address")
    return str(ip)


@contextmanager
def serve_package(data, address, allow_loopback=False):
    address = lan_address(address, allow_loopback)
    route = "/" + secrets.token_urlsafe(24) + "/voice.tar.gz"
    downloaded = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        server_version = "VoicePack"
        sys_version = ""

        def log_message(self, *args):
            pass

        def do_HEAD(self):
            self.deliver(False)

        def do_GET(self):
            self.deliver(True)

        def deliver(self, body):
            self.connection.settimeout(20)
            if self.path != route:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if body:
                try:
                    self.wfile.write(data)
                    self.wfile.flush()
                    downloaded.set()
                except OSError:
                    pass

    server = ThreadingHTTPServer((address, 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://{address}:{server.server_port}{route}", downloaded
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def install_once(client, device, package, url, downloaded, pending, report, timeout=180):
    state = client.snapshot(device)
    preflight(device, state)
    if pending.exists():
        raise InstallerError("pending_exists")
    save_json(pending, {"schema_version": 1, "device_key": device_key(device),
                        "target_sha256": package["sha256"], "outcome": "unknown"})
    try:
        client.install(device, package, url)
    except InstallerError as error:
        if str(error) == "command_rejected":
            pending.unlink()
            raise
        report("checking_after_timeout", None)
    deadline = time.monotonic() + timeout
    started = False
    failures = 0
    previous = None
    while time.monotonic() < deadline:
        try:
            current = client.snapshot(device)
        except InstallerError:
            failures += 1
            if failures >= 3:
                break
            time.sleep(2)
            continue
        failures = 0
        status = current["voice"]
        if current.get("error") != 0:
            break
        if status != previous:
            report("progress", status)
            previous = status
        if status.get("id") == "RU" and status.get("state") in ("downloading", "installing"):
            started = True
        if started and status.get("state") == "fail":
            pending.unlink()
            raise InstallerError("installation_failed")
        if (started and status.get("state") == "success" and status.get("id") == "RU"
                and status.get("progress") == 100 and current.get("language") == "RU"
                and downloaded.is_set()):
            pending.unlink()
            return
        time.sleep(2)
    raise InstallerError("outcome_unknown")
