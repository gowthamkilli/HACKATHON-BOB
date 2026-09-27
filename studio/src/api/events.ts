import type { WitnessEvent } from "./types";

export interface EventStreamHandlers {
  onEvent: (event: WitnessEvent) => void;
  onGap: () => void;
  onOpen?: () => void;
  onClose?: () => void;
}

/**
 * Subscribes to a run's SSE stream. `seq` is gap-free per the backend's contract
 * (engine/events.py) -- this client asserts that and surfaces a reconnect banner the moment it
 * ever sees a gap, per spec section 12.
 */
export function subscribeToRun(runId: string, handlers: EventStreamHandlers): () => void {
  let lastSeq = 0;
  let closed = false;
  let source: EventSource | null = null;

  function connect(fromSeq: number) {
    if (closed) return;
    source = new EventSource(`/api/run/${runId}/events?from_seq=${fromSeq}`);
    source.onopen = () => handlers.onOpen?.();
    source.onmessage = (msg) => {
      const event: WitnessEvent = JSON.parse(msg.data);
      if (lastSeq > 0 && event.seq !== lastSeq + 1) {
        handlers.onGap();
      }
      lastSeq = event.seq;
      handlers.onEvent(event);
    };
    source.onerror = () => {
      source?.close();
      if (!closed) {
        // Reconnect with the last seen seq so we catch up with no duplicates and no gaps.
        setTimeout(() => connect(lastSeq), 1000);
      }
    };
  }

  connect(0);

  return () => {
    closed = true;
    source?.close();
    handlers.onClose?.();
  };
}

/** Replays a stored run's events client-side with the original inter-event timing, so
 * `?run=<id>` is visually indistinguishable from a live run except for the REPLAY badge. */
export async function replayRun(runId: string, onEvent: (event: WitnessEvent) => void): Promise<void> {
  const resp = await fetch(`/api/run/${runId}/events?from_seq=0`);
  const text = await resp.text();
  const events: WitnessEvent[] = text
    .split("\n\n")
    .filter((line) => line.startsWith("data: "))
    .map((line) => JSON.parse(line.slice(6)));

  for (let i = 0; i < events.length; i++) {
    const event = events[i];
    onEvent(event);
    const next = events[i + 1];
    if (next) {
      const delay = Math.min(Math.max((next.ts - event.ts) * 1000, 0), 2000);
      await new Promise((r) => setTimeout(r, delay));
    }
  }
}
