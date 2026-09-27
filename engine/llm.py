"""The one interface every model call in Witness goes through, and its four implementations.

`MockProvider` is the demo-safety mechanism, and it is built honestly: it replays a fixture
recorded from an earlier **live** call (keyed by `sha256(system + user)[:16]`), and raises
`FixtureMissing` on a cache miss rather than inventing a response. A fixture only ever enters
`engine/fixtures/` via an actual `--record` run against a real provider.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional, Protocol


@dataclasses.dataclass
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    elapsed_s: float
    finish_reason: str


class FixtureMissing(Exception):
    """Raised by MockProvider on a cache miss. Never invents a response."""


class Provider(Protocol):
    def complete(
        self, system: str, user: str, *, max_tokens: int, temperature: float,
        stop: Optional[list[str]] = None,
    ) -> Completion: ...


def _fixture_key(system: str, user: str) -> str:
    return hashlib.sha256((system + "\x00" + user).encode("utf-8")).hexdigest()[:16]


class MockProvider:
    """Replays a recording keyed by the exact (system, user) prompt pair. Never fabricates."""

    def __init__(self, fixtures_dir: Path = Path("engine/fixtures")):
        self.fixtures_dir = Path(fixtures_dir)

    def complete(self, system: str, user: str, *, max_tokens: int, temperature: float,
                 stop: Optional[list[str]] = None) -> Completion:
        key = _fixture_key(system, user)
        path = self.fixtures_dir / f"{key}.json"
        if not path.exists():
            raise FixtureMissing(
                f"no recorded fixture for key {key} — run with a live --provider and --record "
                f"to create one; MockProvider never invents a response"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return Completion(**data["completion"])

    def record(self, system: str, user: str, completion: Completion) -> None:
        self.fixtures_dir.mkdir(parents=True, exist_ok=True)
        key = _fixture_key(system, user)
        path = self.fixtures_dir / f"{key}.json"
        path.write_text(json.dumps({
            "system": system, "user": user, "completion": dataclasses.asdict(completion),
        }, indent=2), encoding="utf-8")


class _RecordingWrapper:
    """Wraps a live provider so every real call is also written to `engine/fixtures/`."""

    def __init__(self, inner: Provider, fixtures_dir: Path = Path("engine/fixtures")):
        self.inner = inner
        self.mock = MockProvider(fixtures_dir)

    def complete(self, system: str, user: str, **kwargs) -> Completion:
        completion = self.inner.complete(system, user, **kwargs)
        self.mock.record(system, user, completion)
        return completion


class WatsonxProvider:
    """IBM watsonx.ai, the default provider."""

    def __init__(self):
        self.api_key = os.environ.get("WATSONX_API_KEY")
        self.project_id = os.environ.get("WATSONX_PROJECT_ID")
        self.url = os.environ.get("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
        self.model_id = os.environ.get("WATSONX_MODEL_ID", "ibm/granite-3-8b-instruct")
        if not self.api_key or not self.project_id:
            raise RuntimeError("WATSONX_API_KEY and WATSONX_PROJECT_ID must be set in .env")
        self._model = None

    def _client(self):
        if self._model is None:
            from ibm_watsonx_ai import Credentials
            from ibm_watsonx_ai.foundation_models import ModelInference

            self._model = ModelInference(
                model_id=self.model_id,
                credentials=Credentials(url=self.url, api_key=self.api_key),
                project_id=self.project_id,
            )
        return self._model

    def complete(self, system: str, user: str, *, max_tokens: int, temperature: float,
                 stop: Optional[list[str]] = None) -> Completion:
        model = self._client()
        prompt = f"{system}\n\n{user}"
        start = time.monotonic()
        params = {"max_new_tokens": max_tokens, "temperature": temperature}
        if stop:
            params["stop_sequences"] = stop
        result = model.generate(prompt=prompt, params=params)
        elapsed = time.monotonic() - start
        gen = result["results"][0]
        return Completion(
            text=gen["generated_text"],
            prompt_tokens=gen.get("input_token_count", 0),
            completion_tokens=gen.get("generated_token_count", 0),
            model=self.model_id, elapsed_s=elapsed,
            finish_reason=gen.get("stop_reason", "unknown"),
        )


class AnthropicProvider:
    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY must be set in .env")
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
        self._client = None

    def complete(self, system: str, user: str, *, max_tokens: int, temperature: float,
                 stop: Optional[list[str]] = None) -> Completion:
        import anthropic

        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        start = time.monotonic()
        resp = self._client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
            system=system, messages=[{"role": "user", "content": user}],
            stop_sequences=stop or [],
        )
        elapsed = time.monotonic() - start
        return Completion(
            text="".join(b.text for b in resp.content if b.type == "text"),
            prompt_tokens=resp.usage.input_tokens, completion_tokens=resp.usage.output_tokens,
            model=self.model, elapsed_s=elapsed, finish_reason=resp.stop_reason or "unknown",
        )


class OpenAIProvider:
    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY must be set in .env")
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self._client = None

    def complete(self, system: str, user: str, *, max_tokens: int, temperature: float,
                 stop: Optional[list[str]] = None) -> Completion:
        import openai

        if self._client is None:
            self._client = openai.OpenAI(api_key=self.api_key)
        start = time.monotonic()
        resp = self._client.chat.completions.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            stop=stop or None,
        )
        elapsed = time.monotonic() - start
        choice = resp.choices[0]
        return Completion(
            text=choice.message.content or "",
            prompt_tokens=resp.usage.prompt_tokens, completion_tokens=resp.usage.completion_tokens,
            model=self.model, elapsed_s=elapsed, finish_reason=choice.finish_reason or "unknown",
        )


def get_provider(name: str, *, record: bool = False, fixtures_dir: Path = Path("engine/fixtures")) -> Provider:
    if name == "mock":
        return MockProvider(fixtures_dir)
    live: Provider
    if name == "watsonx":
        live = WatsonxProvider()
    elif name == "anthropic":
        live = AnthropicProvider()
    elif name == "openai":
        live = OpenAIProvider()
    else:
        raise ValueError(f"unknown provider: {name}")
    return _RecordingWrapper(live, fixtures_dir) if record else live
