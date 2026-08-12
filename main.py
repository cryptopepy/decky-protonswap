import asyncio

import decky

from protonswap import (
    REPOS,
    get_available_versions,
    get_compatibilitytools_dir,
    install_version,
    list_installed,
    remove_version,
)


class Plugin:
    """ProtonSwap: manage alternative Proton versions on Steam Deck."""

    async def _main(self):
        self.loop = asyncio.get_event_loop()
        decky.logger.info(
            f"ProtonSwap loaded. Compatibility tools dir: {get_compatibilitytools_dir()}"
        )

    async def _unload(self):
        decky.logger.info("ProtonSwap unloading")

    async def _uninstall(self):
        decky.logger.info("ProtonSwap uninstalled")

    # ---- API exposed to the frontend via @decky/api callable() ----

    async def get_repos(self) -> list:
        """Return the list of supported repositories (id + display name)."""
        return [{"id": repo["id"], "name": repo["name"]} for repo in REPOS]

    async def get_installed(self) -> list:
        """List installed compatibility tools (folder name + version)."""
        return list_installed(get_compatibilitytools_dir())

    async def get_available_versions(self, repo_id: str) -> list:
        """Fetch available versions for a repository (GitHub API)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, get_available_versions, repo_id)

    async def install_version(self, repo_id: str, version: str) -> bool:
        """Download and install a Proton version from a repository."""
        loop = asyncio.get_event_loop()

        def report(percent: int, message: str = ""):
            # Emit progress to the frontend (called from the worker thread).
            self.loop.create_task(
                decky.emit("protonswap_progress", repo_id, version, percent, message)
            )

        return await loop.run_in_executor(
            None, install_version, repo_id, version, report
        )

    async def remove_version(self, folder_name: str) -> bool:
        """Remove an installed compatibility tool by its folder name."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, remove_version, folder_name, get_compatibilitytools_dir()
        )
