# Development

[← Home](README.md) · **English** · [Русский](CONTRIBUTING.ru.md)

## Run checks

Python 3.11+, with no additional dependencies:

```sh
python3 voicepack.py check --lang en
python3 -m unittest discover -s tests -v
```

Checks cover the archive, hashes, metadata, catalog and documentation links, plus installer rejection paths, pending-operation locks, recovery, translations and the local HTTP server. Tests do not contact a robot. CI runs on macOS, Windows and Linux.

## Where things live

| Path | Purpose |
|---|---|
| `installer/` | Cloud client and install/restore logic |
| `installer/messages.en.json` | English interface |
| `installer/messages.ru.json` | Russian interface |
| `voicepack/` | Audio archive, manifest and Russian transcripts |
| `.my_local_dev/` | Local backups and pending-operation records; excluded from Git |

Keep both documentation languages in sync. Message keys and format placeholders must match between languages. Account credentials exist only in memory.

Update the pack, manifest, catalog and samples together. Only claim new compatibility after a device test. There is no automatic publication. See [third-party code](THIRD_PARTY.md) and [audio sources](docs/sources.md).
