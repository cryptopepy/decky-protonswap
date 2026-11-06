# Testing ProtonSwap on a Steam Deck

Build the plugin, get it onto the Deck, then run the checklist at the bottom.

## 1. Build

```bash
pnpm i && pnpm run build     # -> dist/index.js
```

The Python backend needs no build step. It lives in `py_modules/protonswap.py`;
keep it there — decky-loader adds `<plugin_dir>/py_modules` to `sys.path`, and the
decky CLI only packages `dist/`, `bin/`, `defaults/`, `py_modules/` plus the fixed
root files (`main.py`, `package.json`, `plugin.json`, `LICENSE`, `README.md`).
A module at the repo root would be left out of the zip.

Sanity-check the backend without a Deck:

```bash
python3 -m py_compile main.py py_modules/protonswap.py
PYTHONPATH=py_modules python3 -c 'import protonswap as p; print(p.get_compatibilitytools_dir()); print(p.get_available_versions("ge-proton")[:3])'
```

The second command hits the real GitHub API (release metadata only, no downloads).

## 2. Prepare the Deck

1. Settings → System → **Enable Developer Mode**.
2. In Konsole: `passwd` (set a password) and `sudo systemctl start sshd` (enable SSH).
3. Install [Decky Loader](https://wiki.deckbrew.xyz/en/user-guide/home) if it is not already present.

Plugins live in `/home/deck/homebrew/plugins/` (root-owned), and the Decky service
is `plugin_loader`.

## 3. Deploy

### Option A — manual copy over SSH (no Docker needed)

```bash
scp -r dist main.py py_modules package.json plugin.json deck@steamdeck.local:/tmp/ps-src
ssh deck@steamdeck.local 'echo "DECK_PASSWORD" | sudo -S mkdir -p /home/deck/homebrew/plugins/ProtonSwap && \
  echo "DECK_PASSWORD" | sudo -S cp -r /tmp/ps-src/. /home/deck/homebrew/plugins/ProtonSwap/ && \
  echo "DECK_PASSWORD" | sudo -S systemctl restart plugin_loader'
```

`steamdeck.local` may not resolve — use the Deck's IP address.

### Option B — decky CLI (what the VSCode tasks use)

```bash
./.vscode/setup.sh     # downloads the decky CLI into cli/
./.vscode/build.sh     # sudo cli/decky plugin build . -> out/ProtonSwap.zip
```

Then either install `out/ProtonSwap.zip` via Decky → Settings → **Install from
file**, or use the VSCode tasks (requires `.vscode/settings.json`):

1. Copy `.vscode/defsettings.json` to `.vscode/settings.json` and set `deckip`,
   `deckuser`, `deckpass`, `deckkey`. `pluginname` is already `ProtonSwap`.
2. Run task **build** → **deploy** (or **builddeploy**).
3. Run task **restartdecky**.

## 4. Logs

```bash
ssh deck@steamdeck.local 'journalctl -u plugin_loader -n 150 --no-pager'
```

Plugin-specific log files land under `~/homebrew/logs/ProtonSwap/` on the Deck.

## 5. Checklist

1. Quick Access Menu → Decky → **ProtonSwap** opens without a blank panel.
2. **Installed Proton** lists the compatibility tools already in
   `~/.steam/root/compatibilitytools.d/`, each with its `VERSION.txt` value.
3. Pick **GE-Proton** → **Refresh versions** → a version list appears.
4. Install the newest GE-Proton (≈500 MB): progress bar advances, then an
   "Installed" toast, and it appears in the installed list.
5. Restart Steam, open a game → Properties → Compatibility → the new tool is
   selectable.
6. Install a **Proton-CachyOS** build: the offered variant matches the Deck APU
   (`x86_64_v3`).
7. Install **Luxtorpeda** and **Boxtron**: they appear as `luxtorpeda` / `boxtron`
   with the version from the post-install `VERSION.txt`.
8. Remove a tool: confirmation dialog → tool disappears from the list and its
   folder is gone from `compatibilitytools.d/`.
9. Turn Wi-Fi off and refresh versions: an error toast appears instead of a hang.
10. The panel fits at 1280×800 without horizontal scrolling.

## Deck-specific gotchas

- The plugin declares the `root` flag, so decky-loader runs the backend as root
  and sets `HOME` to **root's** home. ProtonSwap therefore resolves the Steam
  directory from `DECKY_USER_HOME` (the deck user's real home) and only falls
  back to `~` when that variable is absent.
- After a successful install the extracted files are chowned to match the owner
  of `compatibilitytools.d/`, so they don't end up root-owned and unmanageable by
  ProtonUp-Qt or the desktop Steam client.
- `py_modules/protonswap.py` must stay in `py_modules/`: decky-loader appends
  `<plugin_dir>/py_modules` to `sys.path`, and the decky CLI only packages that
  directory (plus `dist/`, `bin/`, `defaults/` and the fixed root files).

## Troubleshooting

| Symptom | Check |
|---|---|
| Plugin missing from Decky | Folder name/mode under `~/homebrew/plugins/`, then `journalctl -u plugin_loader` |
| Panel blank / no sections | `dist/index.js` was not copied — rerun `pnpm run build` and redeploy |
| "Failed to load installed" toast | `compatibilitytools.d/` missing or unreadable by the deck user |
| `ModuleNotFoundError: protonswap` | `py_modules/protonswap.py` was not deployed |
| Installed list is empty | Steam never launched, or the Steam root differs — check `DECKY_USER_HOME` |
| Install fails immediately | Network/GitHub rate limit — check the toast text, retry later |
| New tool not in Steam | Restart Steam (compatibility tools are scanned at startup) |
| Tool files owned by root | `ls -l ~/.steam/root/compatibilitytools.d`; this build chowns after extract, so reinstall |
