# ProtonSwap — Decky Loader plugin

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for the
Steam Deck that manages **alternative Proton versions**. It lists the compatibility
tools currently installed in Steam, lets you pick a repository (GE-Proton,
Proton-CachyOS), browse the available versions, download and install one, and remove
installed builds again — all from the Decky quick-access menu.

[![Chat](https://img.shields.io/badge/chat-on%20discord-7289da.svg)](https://deckbrew.xyz/discord)

## What it does

- **List installed Proton versions** — scans Steam's `compatibilitytools.d/`
  directory and shows each installed build (folder name + the version from its
  `VERSION.txt`).
- **Install alternative versions** — choose a repository, load its available
  releases from GitHub, and install any version with one click. Downloads are
  streamed with a progress bar, verified against the release's SHA-512 checksum,
  and extracted safely into `compatibilitytools.d/`.
- **Remove installed versions** — delete a build from the Decky UI (behind a
  confirmation dialog).

Installed tools show up in Steam's game properties like any other compatibility
tool (Properties → Compatibility → Force the use of a specific Steam Play
compatibility tool).

### Supported repositories

The plugin fetches release metadata from each project's public API (GitHub, or
Codeberg for Luxtorpeda) — no API key required, public rate limits apply:

| Repo | Host | Format | Notes |
|------|------|--------|-------|
| **GE-Proton** (`GloriousEggroll/proton-ge-custom`) | GitHub | tar.gz | Official releases, e.g. `GE-Proton9-7` |
| **Proton-CachyOS** (`CachyOS/proton-cachyos`) | GitHub | tar.xz | CPU-optimized; only your arch is offered (Deck ⇒ `x86_64_v3`) |
| **Proton-EM** (`Etaash-mathamsetty/Proton`) | GitHub | tar.xz | Proton fork with Wine-Wayland + FSR4 patches |
| **RTSP Proton** (`SpookySkeletons/proton-ge-rtsp`) | GitHub | tar.gz | GE fork with enhanced Media Foundation (repo moved; redirects followed) |
| **Luxtorpeda** (`luxtorpeda/luxtorpeda`) | Codeberg | tar.xz | Runs native engine ports for classic games |
| **Boxtron** (`dreamer/boxtron`) | GitHub | tar.xz | DOS games via native DOSBox (needs `dosbox`, `inotifywait`, `timidity`) |

More repositories can be added by extending the `REPOS` registry in
`protonswap.py` (URL, archive format, checksum suffix, asset/version parsing,
plus `api_type: "codeberg"` for Codeberg hosts and `install_dir_name` for tools
that install into a fixed folder like Luxtorpeda/Boxtron).

## How it works

- `src/index.tsx` — React UI (installed list, repo/version picker, progress bar,
  toasts) using `@decky/ui` components, sized for the ~400px Decky panel.
- `main.py` — the Decky Python backend: exposes `get_repos`, `get_installed`,
  `get_available_versions`, `install_version`, `remove_version` as async
  callables; streams progress to the UI via `decky.emit("protonswap_progress", …)`.
- `protonswap.py` — pure-stdlib logic (no pip dependencies, runs in Decky's
  minimal Python): Steam-root detection, `compatibilitytools.d` handling,
  GitHub/Codeberg release fetching, checksum verification, safe tar extraction,
  removal.

## Requirements

- Steam Deck with [Decky Loader](https://wiki.deckbrew.xyz/en/user-guide/home) installed.
- Network access to GitHub (api.github.com).
- The plugin's backend runs with root privileges (`_root` flag in `plugin.json`).

## Installation

### From a zip (manual)

1. `pnpm i` and `pnpm run build` (or use a release artifact).
2. Package the plugin into a zip with these files at the archive root:
   `dist/index.js`, `main.py`, `protonswap.py`, `package.json`, `plugin.json`,
   `README.md`, `LICENSE`.
3. On the Deck: Decky Loader → Settings → **Install from file/URL** and select
   the zip.

### Developer install (decky CLI)

```bash
pnpm i                 # install frontend deps
pnpm run build         # build dist/index.js
./.vscode/build.sh     # builds the plugin zip via the decky CLI (needs Docker)
```

The CLI lands in `cli/` after running `./.vscode/setup.sh`. Alternatively copy
the plugin folder (`dist/`, `main.py`, `protonswap.py`, `package.json`,
`plugin.json`) to `~/homebrew/plugins/ProtonSwap/` on the Deck and restart
Decky.

## Development & testing

```bash
pnpm run build     # type-check + bundle the frontend (strict TS) -> dist/
pnpm run watch     # rebuild on change
```

There is no automated test suite (`pnpm test` intentionally fails); the backend
is a standalone stdlib module you can exercise without a Deck:

```bash
python3 -m py_compile main.py protonswap.py
python3 -c 'import protonswap as p; print(p.get_compatibilitytools_dir()); print(p.get_available_versions("ge-proton")[:3])'
```

The second command hits the real GitHub API (release listing only — no large
downloads). A full install/remove roundtrip can be simulated against a temp
directory with a small synthetic tarball; see the smoke tests used during
development.

### On-Deck checklist

Install the plugin, then verify:

1. The Installed list shows real compatibility tools (with `VERSION.txt` versions).
2. Installing a real GE-Proton build (~500 MB) shows progress and a success toast.
3. Installing a Proton-CachyOS build offers the `x86_64_v3` variant.
4. After restarting Steam, the new tool appears in game Properties → Compatibility.
5. Removing a tool deletes its folder and Steam no longer lists it.
6. Network errors surface as toasts (e.g. disable Wi-Fi, then refresh versions).
7. The panel fits comfortably at 1280×800.

## License

BSD-3-Clause, `Copyright (c) 2026, decky-protonswap contributors` (see
`LICENSE`, which also retains the original decky-plugin-template license at the
bottom as required for plugin-store submission). The plugin borrows patterns
from [ProtonUp-Qt](https://github.com/DavidoTek/ProtonUp-Qt) (GPLv3); any code
copied from it must remain GPL-compatible.

## Disclaimer

ProtonSwap is an independent tool and is not affiliated with Valve, GloriousEggroll
(GE-Proton), CachyOS, or the ProtonUp-Qt project.
