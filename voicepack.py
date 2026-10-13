#!/usr/bin/env python3
"""Interactive installer for the tested Dreame r2469x profile."""

import argparse
import getpass
import json
from pathlib import Path
import sys
import warnings

from installer.cloud import DreameCloud, InstallerError
from installer.operations import (
    backup, default_address, install_once, pending_path, preflight,
    recovery_data, serve_package, verify_package,
)
from scripts.check import validate


ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / ".my_local_dev"
MESSAGES = json.loads((ROOT / "installer/messages.en.json").read_text(encoding="utf-8"))


def set_language(language):
    global MESSAGES
    MESSAGES = json.loads((ROOT / "installer" / f"messages.{language}.json").read_text(encoding="utf-8"))


def choose_language():
    while True:
        selected = ask("language_prompt") or "1"
        if selected in ("1", "2"):
            set_language("en" if selected == "1" else "ru")
            return
        say("language_invalid")


def say(key, **values):
    print(MESSAGES.get(key, MESSAGES["unexpected_error"]).format(**values))


def ask(key, **values):
    return input(MESSAGES[key].format(**values)).strip()


def confirm(key):
    return ask(key).casefold() == MESSAGES["yes"].casefold()


def progress(key, status):
    if status is None:
        say(key)
    else:
        value = status.get("progress")
        if type(value) is int and 0 <= value <= 100:
            say("progress", progress=value)


def execute(action, client, device, manifest):
    info = client.info(device)
    state = client.snapshot(info)
    pending = pending_path(LOCAL, info)
    if action == "status":
        voice = state["voice"]
        percent = voice.get("progress")
        say("status", **{key: state[key] for key in ("battery", "language", "state", "error")},
            voice_state=MESSAGES.get("voice_" + str(voice.get("state")), MESSAGES["voice_unknown"]),
            voice_progress=percent if type(percent) is int and 0 <= percent <= 100 else "?")
        if pending.exists():
            say("pending_exists")
        return
    preflight(info, state)
    if action == "locate":
        if confirm("confirm_locate"):
            client.locate(info)
            say("locate_sent")
        return
    if action == "clear-pending":
        if pending.exists() and confirm("confirm_clear"):
            pending.unlink()
            say("pending_cleared")
        return
    if action == "backup":
        say("backup_notice")
        folder = backup(LOCAL, info, state, manifest["stock_restore"])
        say("backup_saved", folder=folder.relative_to(ROOT))
        return
    if pending.exists():
        raise InstallerError("pending_exists")
    if action == "install":
        validate(ROOT)
        package = manifest["package"]
        data = verify_package((ROOT / "voicepack" / package["file"]).read_bytes(), package)
        say("backup_notice")
        folder = backup(LOCAL, info, state, manifest["stock_restore"])
        say("backup_saved", folder=folder.relative_to(ROOT))
    else:
        package = manifest["stock_restore"]
        data = recovery_data(LOCAL, info, package)
    proposed = default_address()
    address = ask("lan_address", address=proposed) or proposed
    say("lan_notice")
    with serve_package(data, address) as (url, downloaded):
        if not confirm("confirm_restore" if action == "restore" else "confirm_install"):
            say("cancelled")
            return
        try:
            info = client.info(device)
            install_once(client, info, package, url, downloaded, pending, progress)
        except (InstallerError, KeyboardInterrupt) as error:
            if pending.exists():
                say("outcome_unknown")
                ask("keep_server")
            raise error
    say("installed")
    if confirm("confirm_locate"):
        client.locate(info)
        say("expected_custom" if action == "install" else "expected_stock")
        say("audible_confirmed" if confirm("confirm_heard") else "audible_unconfirmed")


def main():
    language_parser = argparse.ArgumentParser(add_help=False)
    language_parser.add_argument("--lang", choices=("en", "ru"))
    language_args, _ = language_parser.parse_known_args()
    set_language(language_args.lang or "en")
    if sys.version_info < (3, 11):
        say("python_required")
        return 1
    parser = argparse.ArgumentParser(description=MESSAGES["cli_description"], add_help=False)
    parser.add_argument("-h", "--help", action="help", help=MESSAGES["cli_help"])
    parser.add_argument("--lang", choices=("en", "ru"), help=MESSAGES["cli_language"])
    parser.add_argument("action", nargs="?", default="menu", choices=(
        "menu", "check", "status", "backup", "install", "restore", "locate", "clear-pending",
    ), help=MESSAGES["cli_action"])
    args = parser.parse_args()
    if args.action == "check":
        validate(ROOT)
        say("check_ok")
        return 0
    if not args.lang:
        choose_language()
    manifest = json.loads((ROOT / "voicepack/manifest.json").read_text(encoding="utf-8"))
    say("intro")
    username = ask("username")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass(MESSAGES["password"])
    client = DreameCloud()
    try:
        try:
            client.login(username, password)
        finally:
            del password
        devices = client.devices()
        if not devices:
            raise InstallerError("device_missing")
        for index, device in enumerate(devices, 1):
            name = device.get("customName") or device.get("model") or "Dreame"
            name = "".join(char for char in str(name) if char.isprintable())[:80]
            print(f"{index}. {name}")
        selection = ask("select_device") if len(devices) > 1 else "1"
        if not selection.isdecimal() or not 1 <= int(selection) <= len(devices):
            raise InstallerError("invalid_selection")
        device = devices[int(selection) - 1]
        if args.action != "menu":
            execute(args.action, client, device, manifest)
            return 0
        actions = {"1": "install", "2": "backup", "3": "restore", "4": "status", "5": "locate"}
        while True:
            say("menu")
            selected = ask("choice")
            if selected == "0":
                return 0
            if selected in actions:
                execute(actions[selected], client, device, manifest)
            else:
                say("invalid_selection")
    finally:
        client.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallerError as error:
        say(str(error))
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError):
        say("cancelled")
        raise SystemExit(130)
    except getpass.GetPassWarning:
        say("terminal_required")
        raise SystemExit(1)
    except (OSError, ValueError, KeyError, TypeError):
        say("unexpected_error")
        raise SystemExit(1)
