import { createContext, useContext, useReducer } from "react";
import type { BlastFinding, ConnectRepoResponse, InvariantDelta, LaneResult, Run, WitnessEvent } from "../api/types";
import { STAGES } from "../api/types";

export type StageStatus = "pending" | "running" | "done";

export interface WitnessState {
  repo: ConnectRepoResponse | null;
  currentBranch: string;
  openFilePath: string | null;
  openFileContent: string;
  runId: string | null;
  isReplay: boolean;
  reconnecting: boolean;
  stageStatus: Record<string, StageStatus>;
  agentEvents: Record<string, { started: boolean; done: boolean; findings: BlastFinding[] }>;
  deltas: InvariantDelta[];
  lanes: Record<string, Partial<LaneResult> & { lane_id: string }>;
  finalRun: Run | null;
  terminalLines: string[];
  tokenUsage: { prompt: number; completion: number };
}

const initialState: WitnessState = {
  repo: null,
  currentBranch: "main",
  openFilePath: null,
  openFileContent: "",
  runId: null,
  isReplay: false,
  reconnecting: false,
  stageStatus: Object.fromEntries(STAGES.map((s) => [s, "pending"])),
  agentEvents: {},
  deltas: [],
  lanes: {},
  finalRun: null,
  terminalLines: [],
  tokenUsage: { prompt: 0, completion: 0 },
};

type Action =
  | { type: "REPO_CONNECTED"; repo: ConnectRepoResponse }
  | { type: "OPEN_FILE"; path: string; content: string }
  | { type: "SET_BRANCH"; branch: string }
  | { type: "RUN_STARTED"; runId: string; isReplay: boolean }
  | { type: "WITNESS_EVENT"; event: WitnessEvent }
  | { type: "RECONNECTING"; value: boolean }
  | { type: "RUN_FINISHED"; run: Run }
  | { type: "RESET_RUN" };

function terminalLine(event: WitnessEvent): string | null {
  switch (event.kind) {
    case "stage_start":
      return `[${event.stage}] starting`;
    case "stage_end":
      return `[${event.stage}] done`;
    case "agent_start":
      return `[${event.stage}] ${event.payload.agent} -> thinking`;
    case "agent_end":
      return event.payload.ok
        ? `[${event.stage}] ${event.payload.agent} -> ${event.payload.tokens ?? 0} tok, ${((event.payload.elapsed_s as number) ?? 0).toFixed(1)}s`
        : `[${event.stage}] ${event.payload.agent} -> contributed nothing (${event.payload.error ?? "no output"})`;
    case "lane_start":
      return `[race] ${event.payload.lane_id} racing candidate ${event.payload.candidate_id}`;
    case "lane_base_result":
      return `[race] ${event.payload.lane_id} base -> ${event.payload.result}`;
    case "lane_head_result":
      return `[race] ${event.payload.lane_id} head -> ${JSON.stringify(event.payload.results)}`;
    case "lane_verdict":
      return `[race] ${event.payload.lane_id} verdict -> ${event.payload.verdict}`;
    case "run_end":
      return `[report] run complete`;
    case "error":
      return `[error] ${event.payload.message}`;
    default:
      return null;
  }
}

function reducer(state: WitnessState, action: Action): WitnessState {
  switch (action.type) {
    case "REPO_CONNECTED":
      return { ...state, repo: action.repo, currentBranch: action.repo.head };
    case "OPEN_FILE":
      return { ...state, openFilePath: action.path, openFileContent: action.content };
    case "SET_BRANCH":
      return { ...state, currentBranch: action.branch };
    case "RUN_STARTED":
      return { ...initialStateKeepRepo(state), runId: action.runId, isReplay: action.isReplay };
    case "RECONNECTING":
      return { ...state, reconnecting: action.value };
    case "WITNESS_EVENT": {
      const event = action.event;
      const next: WitnessState = { ...state };
      const line = terminalLine(event);
      if (line) next.terminalLines = [...state.terminalLines, line];

      if (event.kind === "stage_start") {
        next.stageStatus = { ...state.stageStatus, [event.stage]: "running" };
      } else if (event.kind === "stage_end") {
        next.stageStatus = { ...state.stageStatus, [event.stage]: "done" };
      } else if (event.kind === "agent_start") {
        const agent = event.payload.agent as string;
        next.agentEvents = {
          ...state.agentEvents,
          [agent]: { started: true, done: false, findings: state.agentEvents[agent]?.findings ?? [] },
        };
      } else if (event.kind === "agent_end") {
        const agent = event.payload.agent as string;
        next.agentEvents = {
          ...state.agentEvents,
          [agent]: { started: true, done: true, findings: state.agentEvents[agent]?.findings ?? [] },
        };
        if (event.payload.tokens) {
          next.tokenUsage = {
            prompt: state.tokenUsage.prompt,
            completion: state.tokenUsage.completion + (event.payload.tokens as number),
          };
        }
      } else if (event.kind === "lane_start") {
        const laneId = event.payload.lane_id as string;
        next.lanes = { ...state.lanes, [laneId]: { lane_id: laneId, candidate_id: event.payload.candidate_id as string } };
      } else if (event.kind === "lane_base_result") {
        const laneId = event.payload.lane_id as string;
        next.lanes = { ...state.lanes, [laneId]: { ...state.lanes[laneId], base_result: event.payload.result as any } };
      } else if (event.kind === "lane_head_result") {
        const laneId = event.payload.lane_id as string;
        const results = event.payload.results as string[];
        next.lanes = {
          ...state.lanes,
          [laneId]: { ...state.lanes[laneId], head_runs: results as any, head_result: results[results.length - 1] as any },
        };
      } else if (event.kind === "lane_verdict") {
        const laneId = event.payload.lane_id as string;
        next.lanes = { ...state.lanes, [laneId]: { ...state.lanes[laneId], verdict: event.payload.verdict as any } };
      }
      return next;
    }
    case "RUN_FINISHED":
      return { ...state, finalRun: action.run };
    case "RESET_RUN":
      return initialStateKeepRepo(state);
    default:
      return state;
  }
}

function initialStateKeepRepo(state: WitnessState): WitnessState {
  return { ...initialState, repo: state.repo, currentBranch: state.currentBranch };
}

const WitnessContext = createContext<{ state: WitnessState; dispatch: React.Dispatch<Action> } | null>(null);

export function useWitness() {
  const ctx = useContext(WitnessContext);
  if (!ctx) throw new Error("useWitness must be used within WitnessProvider");
  return ctx;
}

export { WitnessContext, reducer, initialState };
export const useWitnessReducer = () => useReducer(reducer, initialState);
