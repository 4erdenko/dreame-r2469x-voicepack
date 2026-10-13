"""Dreamehome EU client; protocol adapted from RoboVoice (see THIRD_PARTY.md)."""

import hashlib
import json
import re
import secrets
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


MODEL = "dreame.vacuum.r2469x"
FIRMWARE = "4.3.9_1642"
BASE = "https://eu.iot.dreame.tech:13267/"
PROPERTIES = {
    "language": (7, 2), "voice": (7, 3), "voice_test": (7, 9),
    "state": (2, 1), "error": (2, 2), "battery": (3, 1),
    "charging": (3, 2), "task": (4, 7),
}


class InstallerError(Exception):
    """A safe error code without credentials or raw server responses."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, url):
        raise InstallerError("redirect_blocked")


class DreameCloud:
    def __init__(self):
        self.token = None
        self.tenant = "000000"
        self.message_id = secrets.randbelow(100) + 1
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))

    def request(self, path, data=None, login=False):
        headers = {
            "User-Agent": "Dreame_Smarthome/2.1.9 (iPhone; iOS 18.4.1; Scale/3.00)",
            "Authorization": "Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg=",
            "Tenant-Id": self.tenant,
            "Content-Type": "application/x-www-form-urlencoded" if login else "application/json",
        }
        if not login:
            if not self.token:
                raise InstallerError("login_required")
            headers["Dreame-Auth"] = self.token
        body = urlencode(data).encode() if login else json.dumps(data).encode()
        try:
            with self.opener.open(Request(BASE + path, data=body, headers=headers), timeout=15) as response:
                payload = response.read(2_000_001)
            if len(payload) > 2_000_000:
                raise InstallerError("invalid_response")
            result = json.loads(payload)
        except HTTPError as error:
            code = error.code
            error.close()
            raise InstallerError("login_failed" if code in (400, 401, 403) else "cloud_failed") from None
        except (URLError, TimeoutError, OSError):
            raise InstallerError("network_failed") from None
        except (ValueError, UnicodeError):
            raise InstallerError("invalid_response") from None
        if not isinstance(result, dict):
            raise InstallerError("invalid_response")
        if login:
            return result
        if result.get("code") != 0 or "data" not in result:
            raise InstallerError("cloud_failed")
        return result["data"]

    def login(self, username, password):
        digest = hashlib.md5((password + "RAylYC%fmSKp7%Tq").encode()).hexdigest()
        result = self.request("dreame-auth/oauth/token", {
            "platform": "IOS", "scope": "all", "grant_type": "password",
            "username": username, "password": digest, "type": "account",
        }, login=True)
        if not isinstance(result.get("access_token"), str) or not result["access_token"]:
            raise InstallerError("login_failed")
        self.token = result["access_token"]
        self.tenant = str(result.get("tenant_id", "000000"))

    def devices(self):
        data = self.request("dreame-user-iot/iotuserbind/device/listV2")
        if not isinstance(data, dict) or not isinstance(data.get("page"), dict):
            raise InstallerError("invalid_response")
        page = data["page"]
        rows = page.get("records")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise InstallerError("invalid_response")
        if int(page.get("total", len(rows))) > len(rows):
            raise InstallerError("device_list_incomplete")
        return [row for row in rows if row.get("model") == MODEL and row.get("did") is not None]

    def info(self, device):
        payload = {"did": str(device["did"])}
        info = self.request("dreame-user-iot/iotuserbind/device/info", payload)
        otc = self.request("dreame-user-iot/iotstatus/devOTCInfo", payload)
        if not isinstance(info, dict) or not isinstance(otc, dict):
            raise InstallerError("invalid_response")
        if str(info.get("did")) != str(device["did"]):
            raise InstallerError("invalid_response")
        nested = otc.get("otcInfo", {})
        if not isinstance(nested, dict):
            raise InstallerError("invalid_response")
        params = nested.get("params", {})
        if not isinstance(params, dict):
            raise InstallerError("invalid_response")
        return {**params, **info}

    def send(self, device, method, params, read_retry=True):
        domain = device.get("bindDomain") or ""
        prefix = domain.split(".")[0] if isinstance(domain, str) else "!"
        if prefix and not re.fullmatch(r"[a-z0-9-]+", prefix):
            raise InstallerError("invalid_response")
        suffix = "-" + prefix if prefix else ""
        did = str(device["did"])
        self.message_id += 1
        data = self.request(f"dreame-iot-com{suffix}/device/sendCommand", {
            "did": did, "id": self.message_id,
            "data": {"did": did, "id": self.message_id, "method": method, "params": params},
        })
        if not isinstance(data, dict) or "result" not in data:
            if method == "get_properties" and read_retry:
                return self.send(device, method, params, read_retry=False)
            raise InstallerError("invalid_response")
        return data["result"]

    def snapshot(self, device):
        rows = self.send(device, "get_properties", [
            {"did": str(device["did"]), "siid": siid, "piid": piid}
            for siid, piid in PROPERTIES.values()
        ])
        if not isinstance(rows, list):
            raise InstallerError("invalid_response")
        values = {}
        for row in rows:
            if not isinstance(row, dict) or row.get("code") != 0:
                raise InstallerError("invalid_response")
            key = (row.get("siid"), row.get("piid"))
            if key in values:
                raise InstallerError("invalid_response")
            values[key] = row.get("value")
        if set(values) != set(PROPERTIES.values()):
            raise InstallerError("invalid_response")
        state = {name: values[key] for name, key in PROPERTIES.items()}
        voice = state["voice"]
        try:
            if isinstance(voice, str):
                try:
                    voice = json.loads(voice)
                except ValueError:
                    voice = json.loads(voice.replace("\\", ""))
            if isinstance(voice, str):
                voice = json.loads(voice)
        except ValueError:
            raise InstallerError("invalid_response") from None
        if not isinstance(voice, dict):
            raise InstallerError("invalid_response")
        state["voice"] = {key: voice.get(key) for key in ("id", "state", "progress")}
        return state

    def install(self, device, package, url):
        value = {"id": "RU", "url": url, "md5": package["md5"], "size": package["size"]}
        result = self.send(device, "set_properties", [{
            "did": str(device["did"]), "siid": 7, "piid": 4,
            "value": json.dumps(value, separators=(",", ":")),
        }])
        if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
            raise InstallerError("invalid_response")
        row = result[0]
        if row.get("siid") != 7 or row.get("piid") != 4 or "code" not in row:
            raise InstallerError("invalid_response")
        if row["code"] != 0:
            raise InstallerError("command_rejected")

    def locate(self, device):
        result = self.send(device, "action", {"did": str(device["did"]), "siid": 7, "aiid": 1, "in": []})
        if not isinstance(result, dict) or result.get("code") != 0:
            raise InstallerError("command_rejected")

    def close(self):
        self.token = None
        self.tenant = "000000"
