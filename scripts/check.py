"""Validate the local voice package without network access or device writes."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import tarfile
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {"find": 45, "cleaning": 129, "washing": 106, "drying": 215}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ogg_headers(data):
    offset = 0
    packet = bytearray()
    headers = []
    while offset < len(data) and len(headers) < 2:
        require(data[offset:offset + 4] == b"OggS", "Invalid Ogg page")
        require(offset + 27 <= len(data), "Truncated Ogg page")
        count = data[offset + 26]
        sizes = data[offset + 27:offset + 27 + count]
        require(len(sizes) == count, "Truncated Ogg segment table")
        offset += 27 + count
        for size in sizes:
            require(offset + size <= len(data), "Truncated Ogg segment")
            packet.extend(data[offset:offset + size])
            offset += size
            if size < 255:
                headers.append(bytes(packet))
                packet.clear()
                if len(headers) == 2:
                    return headers
    raise ValueError("Missing Vorbis headers")


def check_audio(data):
    identification, comments = ogg_headers(data)
    require(len(identification) == 30 and identification[:7] == b"\x01vorbis",
            "Invalid Vorbis identification")
    require(identification[11] == 1, "Audio must be mono")
    require(struct.unpack_from("<I", identification, 12)[0] == 16000,
            "Audio must use 16000 Hz")
    require(comments == b"\x03vorbis" + bytes(8) + b"\x01",
            "Optional audio metadata must be empty")


def check_catalog(rows, audio_ids, package):
    ids = [row["id"] for row in rows]
    require(len(ids) == len(set(ids)) == package["audio_slots"],
            "Duplicate or missing catalogue events")
    require(set(ids) == audio_ids, "Catalogue and archive events differ")
    by_id = {row["id"]: row for row in rows}
    groups = set()
    for row in rows:
        require(bool(row["title"]) and bool(row["text"]), "Empty event text")
        require(row["kind"] in {"donor", "synthesis", "combined", "tone"},
                "Unknown event kind")
        group = tuple(row["same_ids"])
        require(row["id"] in group and len(group) == len(set(group)),
                "Invalid duplicate group")
        for key in group:
            require(key in by_id and by_id[key]["same_ids"] == list(group),
                    "Asymmetric duplicate group")
        require(row["remap_to"] is None or row["remap_to"] in by_id,
                "Missing remap target")
        groups.add(group)
    require(len(groups) == package["unique_audio"], "Unique sound count differs")
    tones = sum(row["kind"] == "tone" for row in rows)
    require(tones == package["original_tones"], "Effect count differs")
    require(len(rows) - tones == package["speech_slots"], "Speech count differs")


def check_links(root):
    for path in root.rglob("*.md"):
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            url = urlsplit(target)
            if url.scheme or not url.path:
                continue
            destination = (path.parent / unquote(url.path)).resolve()
            require(destination.is_relative_to(root), f"Link escapes repository: {target}")
            require(destination.exists(), f"Broken link in {path.name}: {target}")


def validate(root):
    root = root.resolve()
    manifest = json.loads((root / "voicepack/manifest.json").read_text(encoding="utf-8"))
    require(manifest["schema_version"] == 1, "Unsupported manifest schema")
    require(manifest["target"]["model"] == "dreame.vacuum.r2469x", "Wrong model")
    require(manifest["target"]["tested_firmware"] == ["4.3.9_1642"],
            "Firmware evidence requires review")
    package = manifest["package"]
    filename = package["file"]
    require(Path(filename).name == filename and filename.endswith(".tar.gz"),
            "Invalid package filename")
    archive_path = root / "voicepack" / filename
    data = archive_path.read_bytes()
    require(len(data) == package["size"], "Package size mismatch")
    require(hashlib.sha256(data).hexdigest() == package["sha256"],
            "Package SHA-256 mismatch")
    require(hashlib.md5(data).hexdigest() == package["md5"], "Package MD5 mismatch")
    require(data[:3] == b"\x1f\x8b\x08" and data[3] == 0 and data[4:8] == bytes(4),
            "Gzip metadata must be normalized")
    audio = {}
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        names = [item.name for item in members]
        require(len(names) == len(set(names)) == package["member_count"],
                "Duplicate or missing archive members")
        configurations = 0
        for item in members:
            path = PurePosixPath(item.name)
            require(item.isfile() and len(path.parts) == 1 and not path.is_absolute()
                    and ".." not in path.parts, "Archive must contain flat regular files")
            require(item.uid == item.gid == item.mtime == 0
                    and not item.uname and not item.gname and not item.pax_headers,
                    "Tar metadata must be normalized")
            payload = archive.extractfile(item).read()
            if path.suffix == ".ogg":
                require(path.stem.isdecimal(), "Invalid audio event filename")
                key = int(path.stem)
                require(key not in audio, "Duplicate numeric audio event")
                check_audio(payload)
                audio[key] = payload
            elif path.suffix == ".json":
                json.loads(payload)
                configurations += 1
            else:
                require(path.name == "time.txt", "Unexpected archive member")
        require(configurations == 5 and "time.txt" in names,
                "Missing vendor configuration")
    rows = json.loads((root / "voicepack/events.json").read_text(encoding="utf-8"))
    check_catalog(rows, set(audio), package)
    for name, event in SAMPLES.items():
        require((root / "samples" / f"{name}.ogg").read_bytes() == audio[event],
                f"Sample differs from installed package: {name}")
    check_links(root)
    return f"OK: {len(audio)} audio events, {package['unique_audio']} catalogue groups, 4 samples"


if __name__ == "__main__":
    try:
        print(validate(ROOT))
    except (ValueError, KeyError, OSError, tarfile.TarError, struct.error) as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
