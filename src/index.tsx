import {
  ButtonItem,
  Dropdown,
  ModalRoot,
  PanelSection,
  PanelSectionRow,
  Spinner,
  showModal,
  staticClasses,
} from "@decky/ui";
import {
  addEventListener,
  callable,
  definePlugin,
  removeEventListener,
  toaster,
} from "@decky/api";
import { useCallback, useEffect, useState } from "react";
import { FaDownload } from "react-icons/fa";

interface InstalledTool {
  folder: string;
  version: string | null;
}

interface Repo {
  id: string;
  name: string;
}

const getRepos = callable<[], Repo[]>("get_repos");
const getInstalled = callable<[], InstalledTool[]>("get_installed");
const getAvailableVersions = callable<[repoId: string], string[]>(
  "get_available_versions"
);
const installVersion = callable<[repoId: string, version: string], boolean>(
  "install_version"
);
const removeVersion = callable<[folder: string], boolean>("remove_version");

// CachyOS versions are encoded as "<tag>@<arch>" — render them friendlier.
function formatVersion(version: string): string {
  return version.replace("@", " · ");
}

function Content() {
  const [installed, setInstalled] = useState<InstalledTool[] | null>(null);
  const [repos, setRepos] = useState<Repo[]>([]);
  const [repoId, setRepoId] = useState<string | undefined>();
  const [versions, setVersions] = useState<string[] | null>(null);
  const [loadingVersions, setLoadingVersions] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ pct: number; msg: string } | null>(
    null
  );

  const refreshInstalled = useCallback(async () => {
    try {
      setInstalled(await getInstalled());
    } catch (e) {
      toaster.toast({ title: "Error", body: `Failed to load installed: ${e}` });
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setRepos(await getRepos());
      } catch (e) {
        toaster.toast({ title: "Error", body: `Failed to load repositories: ${e}` });
      }
      refreshInstalled();
    })();
    const listener = addEventListener<[string, string, number, string]>(
      "protonswap_progress",
      (_repoId, _version, pct, msg) => {
        setProgress({ pct, msg });
      }
    );
    return () => removeEventListener("protonswap_progress", listener);
  }, [refreshInstalled]);

  const loadVersions = useCallback(async (id: string) => {
    setRepoId(id);
    setLoadingVersions(true);
    setVersions(null);
    try {
      setVersions(await getAvailableVersions(id));
    } catch (e) {
      toaster.toast({ title: "Error", body: `Failed to load versions: ${e}` });
      setVersions([]);
    } finally {
      setLoadingVersions(false);
    }
  }, []);

  const doInstall = async (version: string) => {
    if (!repoId || busy) return;
    setBusy(`Installing ${version}`);
    setProgress({ pct: 0, msg: "Starting" });
    try {
      const ok = await installVersion(repoId, version);
      toaster.toast({
        title: ok ? "Installed" : "Install failed",
        body: formatVersion(version),
      });
      await refreshInstalled();
    } catch (e) {
      toaster.toast({ title: "Install error", body: String(e) });
    } finally {
      setBusy(null);
      setProgress(null);
    }
  };

  const confirmRemove = (tool: InstalledTool) => {
    showModal(
      <ModalRoot
        onOK={async () => {
          setBusy(`Removing ${tool.folder}`);
          try {
            const ok = await removeVersion(tool.folder);
            toaster.toast({
              title: ok ? "Removed" : "Remove failed",
              body: tool.folder,
            });
            await refreshInstalled();
          } catch (e) {
            toaster.toast({ title: "Remove error", body: String(e) });
          } finally {
            setBusy(null);
          }
        }}
      >
        Remove {tool.folder}
        {tool.version ? ` (${tool.version})` : ""}?
      </ModalRoot>
    );
  };

  return (
    <>
      <PanelSection title="Installed Proton">
        {installed === null ? (
          <PanelSectionRow>
            <Spinner />
          </PanelSectionRow>
        ) : installed.length === 0 ? (
          <PanelSectionRow>
            <span style={{ opacity: 0.6 }}>
              No compatibility tools installed.
            </span>
          </PanelSectionRow>
        ) : (
          installed.map((tool) => (
            <PanelSectionRow key={tool.folder}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "8px",
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div
                    style={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {tool.folder}
                  </div>
                  {tool.version && (
                    <div style={{ opacity: 0.6, fontSize: "0.9em" }}>
                      {tool.version}
                    </div>
                  )}
                </div>
                <ButtonItem
                  layout="below"
                  disabled={!!busy}
                  onClick={() => confirmRemove(tool)}
                >
                  Remove
                </ButtonItem>
              </div>
            </PanelSectionRow>
          ))
        )}
      </PanelSection>

      <PanelSection title="Install">
        <PanelSectionRow>
          <Dropdown
            rgOptions={repos.map((r) => ({ data: r.id, label: r.name }))}
            selectedOption={repoId}
            onChange={(opt) => loadVersions(opt.data)}
            strDefaultLabel="Select repository"
            menuLabel="Repository"
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={!repoId || loadingVersions || !!busy}
            onClick={() => loadVersions(repoId!)}
          >
            Refresh versions
          </ButtonItem>
        </PanelSectionRow>
        {loadingVersions ? (
          <PanelSectionRow>
            <Spinner />
          </PanelSectionRow>
        ) : versions !== null && versions.length === 0 ? (
          <PanelSectionRow>
            <span style={{ opacity: 0.6 }}>No versions available.</span>
          </PanelSectionRow>
        ) : (
          versions?.map((version) => (
            <PanelSectionRow key={version}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "8px",
                }}
              >
                <span
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {formatVersion(version)}
                </span>
                <ButtonItem
                  layout="below"
                  disabled={!!busy}
                  onClick={() => doInstall(version)}
                >
                  Install
                </ButtonItem>
              </div>
            </PanelSectionRow>
          ))
        )}
        {progress && (
          <PanelSectionRow>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "4px",
                padding: "8px 0",
              }}
            >
              <span style={{ fontSize: "0.9em", opacity: 0.8 }}>
                {progress.msg} ({progress.pct}%)
              </span>
              <div
                style={{
                  height: "6px",
                  background: "rgba(255,255,255,0.1)",
                  borderRadius: "3px",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    width: `${progress.pct}%`,
                    background: "#7baaf7",
                    transition: "width 0.2s",
                  }}
                />
              </div>
            </div>
          </PanelSectionRow>
        )}
        {busy && (
          <PanelSectionRow>
            <Spinner />
          </PanelSectionRow>
        )}
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  return {
    name: "ProtonSwap",
    titleView: <div className={staticClasses.Title}>ProtonSwap</div>,
    content: <Content />,
    icon: <FaDownload />,
    onDismount() {},
  };
});
