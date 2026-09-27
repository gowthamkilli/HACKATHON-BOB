import type { ConnectRepoResponse, Guarantee, Run, TreeEntry } from "./types";

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`${resp.status} ${path}: ${detail}`);
  }
  return resp.json();
}

export const api = {
  health: () => req<{ ok: boolean; provider: string; model: string; fixtures: boolean }>("/health"),

  connectRepo: (path: string) =>
    req<ConnectRepoResponse>("/repo/connect", { method: "POST", body: JSON.stringify({ path }) }),

  tree: (repoId: string, path = "") =>
    req<{ entries: TreeEntry[] }>(`/repo/${repoId}/tree?path=${encodeURIComponent(path)}`),

  file: (repoId: string, path: string, ref?: string) =>
    req<{ content: string }>(
      `/repo/${repoId}/file?path=${encodeURIComponent(path)}${ref ? `&ref=${encodeURIComponent(ref)}` : ""}`,
    ),

  ledger: (repoId: string) => req<Guarantee[]>(`/repo/${repoId}/ledger`),

  createBranch: (repoId: string, name: string, fromRef: string) =>
    req<{ ok: boolean }>(`/repo/${repoId}/branch`, {
      method: "POST",
      body: JSON.stringify({ name, from_ref: fromRef }),
    }),

  writeFile: (repoId: string, branch: string, path: string, content: string) =>
    req<{ ok: boolean }>(`/repo/${repoId}/file`, {
      method: "PUT",
      body: JSON.stringify({ branch, path, content }),
    }),

  applyPatch: (repoId: string, branch: string, unifiedDiff: string) =>
    req<{ ok: boolean }>(`/repo/${repoId}/patch`, {
      method: "POST",
      body: JSON.stringify({ branch, unified_diff: unifiedDiff }),
    }),

  startPremortem: (repoId: string, base: string, head: string, withRefs: string[] = [], fix = false, provider = "mock") =>
    req<{ run_id: string }>("/run/premortem", {
      method: "POST",
      body: JSON.stringify({ repo_id: repoId, base, head, with_: withRefs, fix, provider }),
    }),

  startPostmortem: (repoId: string, ref: string, incidentText: string, provider = "mock") =>
    req<{ run_id: string }>("/run/postmortem", {
      method: "POST",
      body: JSON.stringify({ repo_id: repoId, ref, incident_text: incidentText, provider }),
    }),

  getRun: (runId: string) => req<Run>(`/run/${runId}`),

  listRuns: () => req<{ run_id: string }[]>("/runs"),

  applyFix: (runId: string) => req<{ ok: boolean }>(`/run/${runId}/fix/apply`, { method: "POST" }),
};
