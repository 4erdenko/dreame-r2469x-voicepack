# Compatibility

[← Home](../README.md) · **English** · [Русский](compatibility.ru.md)

**One device tested:** L10s Ultra Gen 2 · `dreame.vacuum.r2469x` · firmware `4.3.9_1642` · Dreamehome EU.

| Check | Result |
|---|---|
| Custom test phrase | Installation and playback confirmed |
| Earlier partial Maxim pack | Installation and new find-me phrase confirmed |
| Full corrected pack | New `downloading → success` transition, 100%, error 0 |
| Ten revised events on the robot | Not individually listened to |
| Stock RU restore after the test pack | `success`, 100%; sound not separately confirmed |
| Persistence after a reboot | Not tested |
| Other devices, firmware, regions or installers | Not tested |

The pack was installed through the cloud protocol. No root access or firmware flashing was required.

The new local script has been tested for login, device discovery, state reads and saving a stock recovery kit on the real robot. Its full install and restore cycle through the local HTTP server has **not been tested on the device**. Automated tests do not replace that check.

<details>
<summary>Package format & protocol</summary>

- Archive: 564 mono Ogg Vorbis files at 16 kHz; five JSON files and `time.txt` from the official pack.
- MIoT service `7`: language property `2`, status `3`, install `4`, find-me action `1`.
- Install value: a JSON string containing `id`, `url`, `md5`, `size`; `id = RU`.
- A fresh success status and an audible check are required. A previous `success` does not confirm a new installation.
- Original redirects: `298→305`, `112→825`, `140→826`, `17→812`, `19→811`.

Checksums, parameters and stock package: [manifest.json](../voicepack/manifest.json).

</details>
