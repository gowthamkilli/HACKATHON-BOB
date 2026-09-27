"""M0 acceptance test: the event bus is gap-free and disk-faithful under concurrency."""
import json
import threading
import uuid
from pathlib import Path

from engine.events import EventBus


def test_gap_free_seq_under_concurrent_publishers(tmp_path):
    run_id = f"test-{uuid.uuid4().hex[:8]}"
    bus = EventBus(runs_dir=tmp_path)

    collected: list[int] = []
    collected_lock = threading.Lock()

    def collect():
        for event in bus.subscribe(run_id):
            with collected_lock:
                collected.append(event.seq)
                if len(collected) >= 1000:
                    return

    collector = threading.Thread(target=collect)
    collector.start()

    n_threads, per_thread = 5, 200

    def publish_many(worker_id: int):
        for i in range(per_thread):
            bus.publish(run_id, stage="blast", kind="agent_end", payload={"worker": worker_id, "i": i})

    publishers = [threading.Thread(target=publish_many, args=(w,)) for w in range(n_threads)]
    for t in publishers:
        t.start()
    for t in publishers:
        t.join()

    collector.join(timeout=10)
    bus.close(run_id)

    assert len(collected) == n_threads * per_thread
    assert collected == sorted(collected), "seq must arrive in increasing order"
    assert collected == list(range(1, n_threads * per_thread + 1)), "seq must be gap-free 1..N"

    disk_path = tmp_path / f"run-{run_id}.jsonl"
    disk_events = [json.loads(l) for l in disk_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    disk_seqs = [e["seq"] for e in disk_events]
    assert disk_seqs == list(range(1, n_threads * per_thread + 1))
    assert disk_seqs == collected, "jsonl on disk must match the in-memory sequence exactly"
