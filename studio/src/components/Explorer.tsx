import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ConnectRepoResponse, TreeEntry } from "../api/types";
import BranchList from "./BranchList";

interface ExplorerProps {
  repo: ConnectRepoResponse | null;
  currentBranch: string;
  onConnected: (repo: ConnectRepoResponse) => void;
  onBranchSelect: (branch: string) => void;
  onFileOpen: (path: string) => void;
}

function FileTree({ repoId, path, depth, onFileOpen }: { repoId: string; path: string; depth: number; onFileOpen: (p: string) => void }) {
  const [entries, setEntries] = useState<TreeEntry[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    api.tree(repoId, path).then((r) => setEntries(r.entries)).catch(() => setEntries([]));
  }, [repoId, path]);

  return (
    <div>
      {entries.map((entry) => (
        <div key={entry.path}>
          <button
            onClick={() =>
              entry.is_dir
                ? setExpanded((e) => ({ ...e, [entry.path]: !e[entry.path] }))
                : onFileOpen(entry.path)
            }
            style={{ paddingLeft: 8 + depth * 12 }}
            className="w-full text-left flex items-center gap-1.5 py-0.5 text-[13px] text-gray-300 hover:bg-white/5 rounded"
          >
            <span className="text-gray-500 w-3">{entry.is_dir ? (expanded[entry.path] ? "▾" : "▸") : ""}</span>
            <span className="mono truncate">{entry.name}</span>
          </button>
          {entry.is_dir && expanded[entry.path] && (
            <FileTree repoId={repoId} path={entry.path} depth={depth + 1} onFileOpen={onFileOpen} />
          )}
        </div>
      ))}
    </div>
  );
}

export default function Explorer({ repo, currentBranch, onConnected, onBranchSelect, onFileOpen }: ExplorerProps) {
  const [connecting, setConnecting] = useState(false);
  const [pathInput, setPathInput] = useState("samples/orderworks");

  async function connect() {
    setConnecting(true);
    try {
      const result = await api.connectRepo(pathInput);
      onConnected(result);
    } catch (e) {
      alert(`Could not connect: ${(e as Error).message}`);
    } finally {
      setConnecting(false);
    }
  }

  if (!repo) {
    return (
      <div className="w-60 shrink-0 bg-chrome border-r border-border p-4 flex flex-col gap-3">
        <div className="text-sm text-gray-400">No folder connected.</div>
        <input
          value={pathInput}
          onChange={(e) => setPathInput(e.target.value)}
          className="mono text-xs bg-panel border border-border rounded px-2 py-1.5 text-gray-200"
          placeholder="path to repo"
        />
        <button
          onClick={connect}
          disabled={connecting}
          className="bg-accent text-white text-sm rounded px-3 py-1.5 font-medium hover:bg-accent/90 disabled:opacity-50"
        >
          {connecting ? "Connecting…" : "Connect Folder"}
        </button>
      </div>
    );
  }

  return (
    <div className="w-60 shrink-0 bg-chrome border-r border-border flex flex-col overflow-y-auto">
      <div className="px-3 py-2 text-[13px] font-medium text-gray-200 border-b border-border truncate">{repo.name}</div>
      <div className="flex-1 overflow-y-auto py-1">
        <FileTree repoId={repo.repo_id} path="" depth={0} onFileOpen={onFileOpen} />
      </div>
      <div className="border-t border-border">
        <BranchList branches={repo.branches} current={currentBranch} onSelect={onBranchSelect} />
      </div>
    </div>
  );
}
