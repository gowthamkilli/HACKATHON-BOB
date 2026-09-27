"""The subagent harness: render a prompt, call the model, parse the declared return grammar,
retry exactly once on a parse failure, then give up.

Every prompt in `engine/prompts/*.md` is plain `{{placeholder}}` substitution — no Bob-IDE-
specific syntax (see DECISIONS.md's "First action" entry for why). A prompt file's own text
declares its return grammar (e.g. `FINDING_START ... FINDING_END` for the blast-radius agents);
`run_agent` doesn't know or care what that grammar is — the caller supplies `parse_fn`, and
`run_agent` only owns rendering, calling, capping, and the retry-once contract.
"""
from __future__ import annotations

import dataclasses
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

from engine.events import publish
from engine.llm import Provider

PROMPTS_DIR = Path(__file__).parent / "prompts"
MAX_TOKENS_DEFAULT = 800


@dataclasses.dataclass
class AgentResult:
    agent: str
    ok: bool
    parsed: Any
    raw_text: str
    prompt_tokens: int
    completion_tokens: int
    elapsed_s: float
    error: Optional[str] = None


def render_prompt(name: str, context: dict) -> str:
    template = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")

    def _sub(match: re.Match) -> str:
        key = match.group(1).strip()
        return str(context.get(key, f"{{{{MISSING:{key}}}}}"))

    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", _sub, template)


def run_agent(
    name: str, context: dict, *, parse_fn: Callable[[str], Any],
    provider: Provider, bus_run_id: Optional[str] = None, stage: str = "blast",
    max_tokens: int = MAX_TOKENS_DEFAULT, temperature: float = 0.0,
) -> AgentResult:
    rendered = render_prompt(name, context)
    system = f"You are the '{name}' subagent in the Witness pipeline. Follow the return format exactly."

    if bus_run_id:
        publish(bus_run_id, stage, "agent_start", {"agent": name})

    attempt_prompt = rendered
    last_error = None
    for attempt in range(2):
        try:
            completion = provider.complete(
                system=system, user=attempt_prompt, max_tokens=max_tokens, temperature=temperature,
            )
            parsed = parse_fn(completion.text)
            result = AgentResult(
                agent=name, ok=True, parsed=parsed, raw_text=completion.text,
                prompt_tokens=completion.prompt_tokens, completion_tokens=completion.completion_tokens,
                elapsed_s=completion.elapsed_s,
            )
            if bus_run_id:
                publish(bus_run_id, stage, "agent_end", {
                    "agent": name, "ok": True, "tokens": completion.completion_tokens,
                    "elapsed_s": completion.elapsed_s,
                })
            return result
        except Exception as e:  # parse failure OR the provider itself failing (e.g. a mock
            # FixtureMissing) — either way, retry exactly once, then this agent contributed
            # nothing. A missing fixture must degrade to silence, never crash the pipeline.
            last_error = str(e)
            attempt_prompt = (
                f"{rendered}\n\nYour previous response failed to parse: {last_error}\n"
                f"Return ONLY the declared format, nothing else."
            )

    result = AgentResult(
        agent=name, ok=False, parsed=None, raw_text="", prompt_tokens=0, completion_tokens=0,
        elapsed_s=0.0, error=last_error,
    )
    if bus_run_id:
        publish(bus_run_id, stage, "agent_end", {"agent": name, "ok": False, "error": last_error})
    return result


def run_agents_parallel(
    specs: list[dict], *, max_workers: int = 5, provider: Provider,
    bus_run_id: Optional[str] = None, stage: str = "blast",
) -> list[AgentResult]:
    """Each spec: {"name", "context", "parse_fn", optional "max_tokens", "temperature"}."""

    def _one(spec: dict) -> AgentResult:
        return run_agent(
            spec["name"], spec["context"], parse_fn=spec["parse_fn"],
            provider=provider, bus_run_id=bus_run_id, stage=stage,
            max_tokens=spec.get("max_tokens", MAX_TOKENS_DEFAULT),
            temperature=spec.get("temperature", 0.0),
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(_one, specs))
