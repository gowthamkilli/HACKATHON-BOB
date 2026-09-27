import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import { subscribeToRun, replayRun } from "./api/events";
import type { ConnectRepoResponse } from "./api/types";
import Rail from "./components/Rail";
import Explorer from "./components/Explorer";
import EditorPane from "./components/EditorPane";
import DiffPane from "./components/DiffPane";
import TerminalPane from "./components/TerminalPane";
import StatusBar from "./components/StatusBar";
import WitnessPanel from "./components/WitnessPanel";
import { WitnessContext, useWitnessReducer } from "./state/store";

type CenterTab = "editor" | "diff";

export default function App() {
  const [state, dispatch] = useWitnessReducer();
  const [railTab, setRailTab] = useState<"explorer" | "search" | "scm" | "run" | "witness" | "settings">("witness");
  const [centerTab, setCenterTab] = useState<CenterTab>("editor");
  const unsubscribe = useRef<(() => void) | null>(null);

  const params = new URLSearchParams(window.location.search);
  const replayRunId = params.get("run");

  useEffect(() => {
    if (replayRunId) {
      dispatch({ type: "RUN_STARTED", runId: replayRunId, isReplay: true });
      replayRun(replayRunId, (event) => dispatch({ type: "WITNESS_EVENT", event })).then(async () => {
        try {
          const run = await api.getRun(replayRunId);
          dispatch({ type: "RUN_FINISHED", run });
        } catch {
          /* run may not have a final snapshot; the replayed events still populated state */
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [replayRunId]);

  function handleRepoConnected(repo: ConnectRepoResponse) {
    dispatch({ type: "REPO_CONNECTED", repo });
  }

  async function handleFileOpen(path: string) {
    if (!state.repo) return;
    const { content } = await api.file(state.repo.repo_id, path, state.currentBranch);
    dispatch({ type: "OPEN_FILE", path, content });
    setCenterTab("editor");
  }

  function handleProvenanceClick(site: string) {
    const [path] = site.split(":");
    if (path) handleFileOpen(path);
  }

  async function fetchFinishedRun(runId: string, attemptsLeft = 8): Promise<void> {
    // The "run_end" event fires from inside run_premortem() a moment before the server's
    // background thread finishes storing the full Run object -- so the very first GET can
    // still see the earlier {run_id, status} placeholder shape. Retry briefly rather than
    // rendering that partial shape as if it were a finished Run.
    const run = await api.getRun(runId);
    if ((run as unknown as { ledger?: unknown }).ledger === undefined && attemptsLeft > 0) {
      await new Promise((r) => setTimeout(r, 250));
      return fetchFinishedRun(runId, attemptsLeft - 1);
    }
    dispatch({ type: "RUN_FINISHED", run });
  }

  function handleStartRun(runId: string, isReplay: boolean) {
    unsubscribe.current?.();
    dispatch({ type: "RUN_STARTED", runId, isReplay });
    unsubscribe.current = subscribeToRun(runId, {
      onEvent: (event) => {
        dispatch({ type: "WITNESS_EVENT", event });
        if (event.kind === "run_end") {
          fetchFinishedRun(runId);
        }
      },
      onGap: () => dispatch({ type: "RECONNECTING", value: true }),
      onOpen: () => dispatch({ type: "RECONNECTING", value: false }),
    });
  }

  useEffect(() => () => unsubscribe.current?.(), []);

  return (
    <WitnessContext.Provider value={{ state, dispatch }}>
      <div className="h-screen flex flex-col bg-chrome">
        <div className="flex-1 flex min-h-0">
          <Rail active={railTab} onSelect={setRailTab} />
          <Explorer
            repo={state.repo}
            currentBranch={state.currentBranch}
            onConnected={handleRepoConnected}
            onBranchSelect={(b) => dispatch({ type: "SET_BRANCH", branch: b })}
            onFileOpen={handleFileOpen}
          />

          <div className="flex-1 flex flex-col min-w-0 bg-panel">
            <div className="flex border-b border-border shrink-0">
              {(["editor", "diff"] as CenterTab[]).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setCenterTab(tab)}
                  className={`px-3 py-1.5 text-[12px] border-r border-border ${
                    centerTab === tab ? "bg-panel text-gray-100" : "bg-chrome text-gray-500 hover:text-gray-300"
                  }`}
                >
                  {tab === "editor" ? state.openFilePath ?? "untitled" : "Diff: base ↔ head"}
                </button>
              ))}
            </div>

            {centerTab === "editor" ? (
              <EditorPane
                path={state.openFilePath}
                content={state.openFileContent}
                onChange={(v) => dispatch({ type: "OPEN_FILE", path: state.openFilePath ?? "", content: v })}
              />
            ) : (
              <DiffPane
                baseLabel={state.finalRun?.base_ref ?? "base"}
                headLabel={state.finalRun?.head_ref ?? "head"}
                baseContent={state.openFileContent}
                headContent={state.openFileContent}
              />
            )}

            <TerminalPane lines={state.terminalLines} />
          </div>

          <WitnessPanel
            repoId={state.repo?.repo_id ?? null}
            base={state.currentBranch}
            branches={state.repo?.branches ?? []}
            onStartRun={handleStartRun}
            onProvenanceClick={handleProvenanceClick}
          />
        </div>

        <StatusBar branch={state.currentBranch} findingsCount={state.finalRun?.findings?.defeated?.length ?? 0} />
      </div>
    </WitnessContext.Provider>
  );
}
