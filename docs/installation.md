# Install & restore

[← Home](../README.md) · **English** · [Русский](installation.ru.md)

The pack and its transcripts are in Russian. Changing the interface language does not change the audio.

## 1. Prepare

- Install [Python 3.11+](https://www.python.org/downloads/), download this repository as a ZIP, and extract it into a writable folder.
- Connect the computer and robot to the same home network. Internet access is also required.
- Dock the robot and charge it to at least **50%**. Stop cleaning and wait for any update to finish.
- Check your profile: **L10s Ultra Gen 2 · `r2469x` · `4.3.9_1642` · Dreamehome EU**.

## 2. Launch

| System | Open or run |
|---|---|
| macOS | `start.command` |
| Windows | `start.cmd` |
| Linux | `sh start.sh` |

Choose **English** or **Русский**, then enter your Dreamehome login and password.
The password is hidden while you type and is not saved.

If the launcher does not open, use `python3 voicepack.py` in that folder. On Windows, use `py -3 voicepack.py`.

## 3. Install

Choose **1 — Install voice pack**. The script checks the pack and robot, then saves a recovery kit.

Confirm the computer's local IP address and the installation. Allow Python incoming connections on your **private network** if the firewall asks. Keep the window open until the operation finishes.

When prompted, play the test phrase. You should hear Maxim say:

> «Надеюсь, удастся тихо прошмыгнуть»
> — “I hope I can sneak past quietly.”

A successful status still needs an audible check. [What has been tested →](compatibility.md)

## Backup & restore

| Menu option | What it does |
|---|---|
| **2 — Save recovery kit** | Downloads and verifies the official Russian voice pack; saves the robot's state. |
| **3 — Restore stock Russian voice** | Verifies the saved pack and installs it on the same robot. |

Keep `.my_local_dev/backups/` if you move the installer to another folder or computer.
This kit restores the stock voice: it cannot extract or restore an arbitrary custom voice previously on the robot. The vendor archive is kept byte for byte.

## Need help?

| Problem | What to do |
|---|---|
| Python is missing | Install Python 3.11+ using the link above. |
| Certificate error on macOS | Run `Install Certificates.command` from your Python installation. Keep TLS verification enabled. |
| Robot is missing or unsupported | Check the account, EU region, model and firmware in Dreamehome. |
| Robot cannot download the pack | Check the computer's IP address, VPN, firewall and guest Wi-Fi isolation. No router port forwarding is needed. |
| Result is unknown | Wait for the download to finish in Dreamehome. Keep this window open; press Enter only after the download has finished. Do not start another installation or restore. |

<details>
<summary>Clear a pending operation</summary>

First check in Dreamehome that the previous download has ended. Then run:

```sh
python3 voicepack.py clear-pending --lang en
```

On Windows, replace `python3` with `py -3`. The script checks the robot again and asks for confirmation. Clearing the local lock does not install anything or prove that the previous operation succeeded.

</details>

<details>
<summary>Choose the language from the command line</summary>

Use `python3 voicepack.py --lang en` for English or `python3 voicepack.py --lang ru` for Russian.

</details>
