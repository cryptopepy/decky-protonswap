"""ProtonSwap backend logic.

Pure stdlib (urllib, tarfile, hashlib, shutil) so it runs in decky-loader's
minimal Python environment and can be tested standalone (no decky dependency).
Progress is reported through an optional callback wired to decky.emit in main.py.

Logic mirrors ProtonUp-Qt (pupgui2/util.py, constants.py, resources/ctmods/).
"""

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Steam install locations, mirroring ProtonUp-Qt pupgui2/constants.py
# `_POSSIBLE_STEAM_ROOTS`. The first existing one wins.
_STEAM_ROOT_CANDIDATES = [
    os.path.realpath(os.path.join(os.path.expanduser("~"), root))
    for root in [
        ".local/share/Steam",
        ".steam/root",
        ".steam/steam",
        ".steam/debian-installation",
    ]
]

COMPAT_TOOLS_SUBDIR = "compatibilitytools.d"


# ---------------------------------------------------------------------------
# Hardware capabilities / CachyOS helpers (ported from ctmod_protoncachyos)
# ---------------------------------------------------------------------------

def get_hwcaps() -> set:
    """Return the CPU hardware capabilities, e.g. {'x86_64', 'x86_64_v3'}.

    Port of ProtonUp-Qt ctmod_protoncachyos.get_hwcaps. Requires /proc/cpuinfo
    (Linux); falls back to plain x86_64 elsewhere so the module stays testable.
    """
    hwcaps = {"x86_64"}
    flags_v2 = {"sse4_1", "sse4_2", "ssse3"}
    flags_v3 = {*flags_v2, "avx", "avx2"}
    flags_v4 = {*flags_v3, "avx512f", "avx512bw", "avx512cd", "avx512dq", "avx512vl"}
    cpuinfo = "/proc/cpuinfo"
    if os.path.exists(cpuinfo):
        with open(cpuinfo, "r", errors="replace") as f:
            for line in f:
                if line.startswith("flags"):
                    flags = set(line.split(":")[1].strip().split())
        if flags_v4.issubset(flags):
            hwcaps.add("x86_64_v4")
        if flags_v3.issubset(flags):
            hwcaps.add("x86_64_v3")
        if flags_v2.issubset(flags):
            hwcaps.add("x86_64_v2")
    return hwcaps


def _cachyos_version_to_tag(version: str) -> str:
    """'cachyos-11.0-20260703-slr@x86_64_v3' -> 'cachyos-11.0-20260703-slr'.

    Versions are encoded as '<tag>@<arch>'; the tag is what GitHub's
    releases API resolves.
    """
    return version.split("@", 1)[0]


def _cachyos_asset_match(asset: dict, version: str) -> bool:
    """Pick the CachyOS asset matching the CPU architecture in the version.

    Real asset names are 'proton-cachyos-<tag>-<arch>.tar.xz' and
    '...-<arch>.sha512sum' (e.g. -x86_64_v3.tar.xz)."""
    if "browser_download_url" not in asset:
        return False
    arch = version.split("@", 1)[-1]
    name = asset["name"]
    return name.endswith(f"{arch}.tar.xz") or name.endswith(f"{arch}.sha512sum")


def _cachyos_list_versions(api_url: str) -> list:
    """List CachyOS versions the current CPU supports.

    Returns ['<tag>@<arch>', ...], e.g. ['cachyos-11.0-20260703-slr@x86_64_v3'].
    Note: the vendored ctmod_protoncachyos parsing is stale for current
    releases (asset names are now 'proton-cachyos-<tag>-<arch>.tar.xz'), so
    this parser extracts the tag + arch directly from the asset name.
    """
    hwcaps = get_hwcaps()
    prefix = "proton-cachyos-"
    versions = []
    releases = _github_get_json(f"{api_url}?per_page=100&page=1")
    for release in releases:
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if not name.endswith(".tar.xz") or not name.startswith(prefix):
                continue
            rest = name[len(prefix) : -len(".tar.xz")]
            parts = rest.split("-")
            if len(parts) < 2:
                continue
            arch = parts[-1]
            if arch not in hwcaps:
                continue
            tag = "cachyos-" + "-".join(parts[:-1])
            version = f"{tag}@{arch}"
            if version not in versions:
                versions.append(version)
    return versions


# ---------------------------------------------------------------------------
# Repository registry, mirroring ProtonUp-Qt ctmods. One entry per repo:
#   id             - stable identifier used by the frontend
#   name           - display name
#   api_url        - GitHub releases API URL
#   release_format - archive extension to extract ("tar.gz", "tar.xz")
#   checksum_suffix - checksum asset suffix used for verification
#   asset_match    - optional callable(asset, version) -> bool to pick the
#                    download/checksum asset for a specific version
#                    (default: name ends with release_format / checksum_suffix)
#   list_versions  - optional callable(api_url) -> list[str] overriding the
#                    generic "release tag == version" listing
#   version_to_tag - optional callable(version) -> tag for the release lookup
REPOS = [
    {
        "id": "ge-proton",
        "name": "GE-Proton",
        "api_url": "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases",
        "release_format": "tar.gz",
        "checksum_suffix": ".sha512sum",
        "asset_match": lambda asset, version: "browser_download_url" in asset
        and "aarch64" not in asset["browser_download_url"],
        "list_versions": None,
        "version_to_tag": None,
    },
    {
        "id": "proton-cachyos",
        "name": "Proton-CachyOS",
        "api_url": "https://api.github.com/repos/CachyOS/proton-cachyos/releases",
        "release_format": "tar.xz",
        "checksum_suffix": ".sha512sum",
        "asset_match": _cachyos_asset_match,
        "list_versions": _cachyos_list_versions,
        "version_to_tag": _cachyos_version_to_tag,
    },
]

# Size of the buffer used when streaming downloads.
BUFFER_SIZE = 65536


# ---------------------------------------------------------------------------
# Steam / compatibility tools directory discovery (phase 2)
# ---------------------------------------------------------------------------

def get_compatibilitytools_dir() -> str:
    """Return the Steam compatibilitytools.d directory (creates nothing).

    Mirrors ProtonUp-Qt's _POSSIBLE_STEAM_ROOTS detection: the first existing
    Steam root wins (the candidates are usually symlinks to the same place);
    falls back to the most common location so there is still a valid target
    before Steam has been launched once.
    """
    for root in _STEAM_ROOT_CANDIDATES:
        if os.path.isdir(root):
            return os.path.join(root, COMPAT_TOOLS_SUBDIR)
    return os.path.join(_STEAM_ROOT_CANDIDATES[0], COMPAT_TOOLS_SUBDIR)


def _sort_compatibility_tool_names(names: list, reverse: bool = True) -> list:
    """Sort compatibility tool folder names (port of ProtonUp-Qt
    sort_compatibility_tool_names): alphabetical base order, then version-aware
    so 'Proton 9.0-x' sorts before 'Proton 8.0-x' and GE-Proton builds last.
    Default newest-first for display."""
    names = sorted(names)
    ver_dict = {}
    for i, name in enumerate(names, start=1):
        if name.startswith("GE-Proton") or "SteamTinkerLaunch" in name:
            ver_dict[100 + i] = name
        elif "Proton-" in name:
            try:
                ver_string = name.split("-")[1]
                ver_major = int(ver_string.split(".")[0])
                ver_minor = int(ver_string.split(".")[1])
                ver_dict[ver_major * 10 + ver_minor] = name
            except (IndexError, ValueError):
                ver_dict[i] = name
        else:
            ver_dict[i] = name
    ordered = [ver_dict[key] for key in sorted(ver_dict)]
    if reverse:
        ordered.reverse()
    return ordered


def list_installed(install_dir: str) -> list:
    """Return installed compatibility tools as [{folder, version}, ...].

    Port of ProtonUp-Qt get_installed_ctools: scans the directory, skips
    non-directories, and reads VERSION.txt when present. Sorted newest-first.
    """
    ctools = []
    if os.path.isdir(install_dir):
        for folder in _sort_compatibility_tool_names(os.listdir(install_dir)):
            folder_path = os.path.join(install_dir, folder)
            if not os.path.isdir(folder_path):
                continue
            version = None
            ver_file = os.path.join(folder_path, "VERSION.txt")
            if os.path.exists(ver_file):
                with open(ver_file, "r", encoding="utf-8", errors="replace") as f:
                    version = f.read().strip() or None
            ctools.append({"folder": folder, "version": version})
    return ctools


# ---------------------------------------------------------------------------
# Repo release fetching / install / remove (phase 3)
# ---------------------------------------------------------------------------

def _github_get_json(url: str):
    """GET a GitHub API URL and return the parsed JSON (stdlib urllib only).

    Raises RuntimeError on HTTP/network errors and on GitHub API rate limiting
    (mirrors ProtonUp-Qt's ghapi_rlcheck behaviour).
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "decky-protonswap",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub API error {e.code} for {url}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error fetching {url}: {e.reason}") from e
    if isinstance(data, dict) and "API rate limit exceeded" in data.get("message", ""):
        raise RuntimeError("GitHub API rate limit exceeded")
    return data


def _get_repo(repo_id: str) -> dict:
    """Look up a repository by id; raise ValueError if unknown."""
    for repo in REPOS:
        if repo["id"] == repo_id:
            return repo
    raise ValueError(f"unknown repository: {repo_id}")


def get_available_versions(repo_id: str) -> list:
    """Return available versions for a repository (GitHub API, stdlib only).

    Synchronous by design: main.py runs it via asyncio's run_in_executor so the
    event loop is never blocked. Mirrors ProtonUp-Qt fetch_project_releases.
    """
    repo = _get_repo(repo_id)
    if repo["list_versions"]:
        return repo["list_versions"](repo["api_url"])
    # Generic GitHub path: version == release tag (GE-Proton).
    releases = _github_get_json(f"{repo['api_url']}?per_page=100&page=1")
    return [
        r["tag_name"]
        for r in releases
        if "tag_name" in r and r["tag_name"] != "latest"
    ]


def _github_get_text(url: str) -> str:
    """GET a URL and return raw text (used for checksum assets, not JSON)."""
    req = urllib.request.Request(url, headers={"User-Agent": "decky-protonswap"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_release_data(repo: dict, version: str) -> dict:
    """Fetch download/checksum info for a version of a repo.

    Port of ProtonUp-Qt fetch_project_release_data: resolves the tag, then
    picks the asset whose name matches the release format / checksum suffix
    and passes the repo's asset_match.
    """
    tag = repo["version_to_tag"](version) if repo["version_to_tag"] else version
    release = _github_get_json(f"{repo['api_url']}/tags/{tag}")
    values = {
        "version": release.get("tag_name", tag),
        "date": (release.get("published_at") or "")[:10],
    }
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if not repo["asset_match"](asset, version):
            continue
        if name.endswith(repo["release_format"]) and "download" not in values:
            values["download"] = asset["browser_download_url"]
            values["size"] = asset.get("size")
        elif name.endswith(repo["checksum_suffix"]) and "checksum" not in values:
            values["checksum"] = asset["browser_download_url"]
    return values


def _download_file(url: str, destination: str, progress=None) -> bool:
    """Stream a file to destination with progress(percent, message) callbacks."""
    req = urllib.request.Request(url, headers={"User-Agent": "decky-protonswap"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(destination, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(BUFFER_SIZE)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(min(int(done * 100 / total), 100), "Downloading")
        return True
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return False


def _sha512sum(path: str) -> str:
    """Return the hex SHA-512 of a file (port of ctmod __sha512sum)."""
    digest = hashlib.sha512()
    with open(path, "rb") as f:
        while chunk := f.read(BUFFER_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_tar(tar_path: str, extract_path: str, mode: str = "r:") -> bool:
    """Extract a tar archive, rejecting path traversal (absolute / '..' paths)."""
    if not mode.startswith("r:"):
        mode = f"r:{mode}"
    try:
        with tarfile.open(tar_path, mode) as tf:
            for member in tf.getmembers():
                if os.path.isabs(member.name) or ".." in member.name.split("/"):
                    return False
            tf.extractall(extract_path)
        return True
    except (tarfile.TarError, OSError):
        return False


def install_version(repo_id: str, version: str, progress=None) -> bool:
    """Download, verify and install a Proton version into compatibilitytools.d.

    progress(percent, message) is optional; main.py wires it to decky.emit.
    Returns True on success, False on any failure (including already installed).
    """
    def report(percent: int, message: str = ""):
        if progress:
            progress(percent, message)

    repo = _get_repo(repo_id)
    install_dir = get_compatibilitytools_dir()
    tag = repo["version_to_tag"](version) if repo["version_to_tag"] else version
    target = os.path.join(install_dir, tag)
    if os.path.isdir(target):
        report(0, "Already installed")
        return False

    try:
        data = _fetch_release_data(repo, version)
    except RuntimeError as e:
        report(0, str(e))
        return False
    if "download" not in data:
        report(0, "No downloadable asset for this version")
        return False

    report(5, "Downloading")
    tmp = tempfile.mkdtemp(prefix="protonswap-")
    try:
        archive = os.path.join(tmp, data["download"].split("/")[-1])
        if not _download_file(data["download"], archive, progress):
            report(0, "Download failed")
            return False

        if "checksum" in data:
            report(90, "Verifying checksum")
            try:
                source_checksum = _github_get_text(data["checksum"])
            except (urllib.error.HTTPError, urllib.error.URLError):
                source_checksum = ""
            local_checksum = _sha512sum(archive)
            if source_checksum and local_checksum not in source_checksum:
                report(0, "Checksum mismatch")
                return False

        report(95, "Extracting")
        mode = "r:" + repo["release_format"].rsplit(".", 1)[-1]  # r:gz / r:xz
        os.makedirs(install_dir, exist_ok=True)
        if not _extract_tar(archive, install_dir, mode):
            report(0, "Extraction failed")
            return False

        # Keep the verified checksum next to the install (like ProtonUp-Qt)
        # so future installs can detect an identical already-installed build.
        checksum_file = os.path.join(target, "sha512sum")
        if "checksum" in data and os.path.exists(checksum_file):
            with open(checksum_file, "w") as f:
                f.write(local_checksum)

        report(100, "Installed")
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def remove_version(folder_name: str, install_dir: str) -> bool:
    """Remove an installed compatibility tool by its folder name.

    Port of ProtonUp-Qt remove_ctool (without the SteamTinkerLaunch special
    case, which is out of scope). Rejects path traversal / absolute paths.
    """
    target = os.path.join(install_dir, folder_name)
    if (
        os.path.isabs(folder_name)
        or ".." in folder_name.split("/")
        or os.path.basename(folder_name) != folder_name
    ):
        return False
    if os.path.isdir(target):
        shutil.rmtree(target)
        return True
    return False
