"""The event bus every pipeline stage publishes to.

There is no compute-silently-then-render path anywhere in Witness: every stage of the
pipeline (intake, blast, delta, race, confirm, fix, report) calls `publish` as it works, and
the UI (or a replaying CLI) watches the pipeline think via `subscribe`.

Guarantees:
- `seq` is per-run, monotonic, and gap-free, even under concurrent publishers.
- Every publish is appended to `runs/run-<id>.jsonl` before `publish` returns, so a killed run
  leaves a readable partial file and a reconnecting client can replay from any `seq`.
"""
from __future__ import annotations

import collections
import json
import queue
import threading
import time
from pathlib import Path
from typing import Iterator, Optional

from engine.schemas import Event

RUNS_DIR = Path("runs")
RING_BUFFER_SIZE = 4096


class _RunBus:
    def __init__(self, run_id: str, runs_dir: Path):
        self.run_id = run_id
        self.lock = threading.Lock()
        self.next_seq = 1
        self.ring: collections.deque[Event] = collections.deque(maxlen=RING_BUFFER_SIZE)
        self.subscribers: list["queue.Queue[Optional[Event]]"] = []
        runs_dir.mkdir(parents=True, exist_ok=True)
        self.path = runs_dir / f"run-{run_id}.jsonl"
        self._fh = open(self.path, "a", encoding="utf-8")

    def publish(self, stage: str, kind: str, payload: dict) -> Event:
        with self.lock:
            seq = self.next_seq
            self.next_seq += 1
            event = Event(run_id=self.run_id, seq=seq, ts=time.time(), stage=stage, kind=kind, payload=payload)
            line = json.dumps(event.to_dict(), separators=(",", ":"))
            self._fh.write(line + "\n")
            self._fh.flush()
            self.ring.append(event)
            for sub in list(self.subscribers):
                sub.put(event)
            return event

    def subscribe(self) -> "queue.Queue[Optional[Event]]":
        q: "queue.Queue[Optional[Event]]" = queue.Queue()
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[Optional[Event]]") -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def close(self) -> None:
        with self.lock:
            self._fh.close()
            for sub in self.subscribers:
                sub.put(None)


class EventBus:
    """Process-wide registry of one `_RunBus` per active run_id."""

    def __init__(self, runs_dir: Path = RUNS_DIR):
        self._runs_dir = runs_dir
        self._lock = threading.Lock()
        self._buses: dict[str, _RunBus] = {}

    def _get_or_create(self, run_id: str) -> _RunBus:
        with self._lock:
            bus = self._buses.get(run_id)
            if bus is None:
                bus = _RunBus(run_id, self._runs_dir)
                self._buses[run_id] = bus
            return bus

    def publish(self, run_id: str, stage: str, kind: str, payload: dict) -> Event:
        return self._get_or_create(run_id).publish(stage, kind, payload)

    def subscribe(self, run_id: str, from_seq: int = 0) -> Iterator[Event]:
        """Yields events for `run_id`, starting from `from_seq` (0 = from the start).

        Replays whatever is already on disk first (so a reconnecting client with `from_seq`
        catches up with no duplicates and no gaps), then switches to live events.
        """
        # Register as a live subscriber BEFORE reading the disk snapshot, so no event
        # published from this point on can fall in the gap between "read the file" and
        # "start listening" — the queue buffers it, and the seen_seq high-water mark below
        # dedups anything the disk read already yielded.
        bus = self._get_or_create(run_id)
        q = bus.subscribe()
        seen_seq = 0
        try:
            path = self._runs_dir / f"run-{run_id}.jsonl"
            if path.exists():
                with open(path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        event = Event.from_dict(json.loads(line))
                        if event.seq > seen_seq:
                            seen_seq = event.seq
                        if event.seq > from_seq:
                            yield event

            while True:
                event = q.get()
                if event is None:
                    return
                if event.seq > seen_seq and event.seq > from_seq:
                    seen_seq = event.seq
                    yield event
        finally:
            bus.unsubscribe(q)

    def close(self, run_id: str) -> None:
        with self._lock:
            bus = self._buses.pop(run_id, None)
        if bus is not None:
            bus.close()


_default_bus = EventBus()


def publish(run_id: str, stage: str, kind: str, payload: Optional[dict] = None) -> Event:
    return _default_bus.publish(run_id, stage, kind, payload or {})


def subscribe(run_id: str, from_seq: int = 0) -> Iterator[Event]:
    return _default_bus.subscribe(run_id, from_seq=from_seq)


def close(run_id: str) -> None:
    _default_bus.close(run_id)
