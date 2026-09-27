"""Witness CLI — the single entry point, per WITNESS-BUILD-SPEC.md §8.

    witness premortem  --repo P --base main --head B [--with B2 ...] [--fix] [--provider X]
    witness postmortem --repo P --incident FILE [--ref HEAD] [--provider X]
    witness standing   --repo P --ref HEAD [--provider X]
    witness bench      --repo P [--provider X]
    witness replay     --run ID
    witness serve       [--port 8787]

This module only parses arguments and dispatches. Each subcommand's real logic lives in the
module named after it (engine.race / engine.confirm for the race, engine.bench, etc.) and is
filled in milestone by milestone — nothing here is faked to look like it works ahead of the
milestone that actually builds it.
"""
from __future__ import annotations

import argparse
import sys

PROVIDERS = ("watsonx", "anthropic", "openai", "mock")


def _add_provider_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--provider", choices=PROVIDERS, default="watsonx")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="witness", description="Pre-merge logic-break gate.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("premortem", help="Prove a branch pair breaks a documented guarantee.")
    p.add_argument("--repo", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--with", dest="with_refs", action="append", default=[])
    p.add_argument("--fix", action="store_true")
    _add_provider_arg(p)

    p = sub.add_parser("postmortem", help="Reproduce a reported incident as a failing test.")
    p.add_argument("--repo", required=True)
    p.add_argument("--incident", required=True)
    p.add_argument("--ref", default="HEAD")
    _add_provider_arg(p)

    p = sub.add_parser("standing", help="Scan a single ref for undefended/contradicted guarantees.")
    p.add_argument("--repo", required=True)
    p.add_argument("--ref", default="HEAD")
    _add_provider_arg(p)

    p = sub.add_parser("bench", help="Run the full benchmark corpus and write bench/RESULTS.md.")
    p.add_argument("--repo", required=True)
    _add_provider_arg(p)

    p = sub.add_parser("replay", help="Re-emit a stored run's events with zero model calls.")
    p.add_argument("--run", required=True)

    p = sub.add_parser("serve", help="Start the FastAPI server backing Witness Studio.")
    p.add_argument("--port", type=int, default=8787)

    return parser


def _require_credentials_or_mock(provider: str) -> None:
    """§8: never silently fall back to a replay. Exit 2 with the exact documented message."""
    if provider == "mock":
        return
    import os

    have_watsonx = bool(os.environ.get("WATSONX_API_KEY"))
    have_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    have_openai = bool(os.environ.get("OPENAI_API_KEY"))
    configured = {"watsonx": have_watsonx, "anthropic": have_anthropic, "openai": have_openai}
    if not configured.get(provider, False):
        print("no model configured — set WATSONX_API_KEY in .env, or run with --provider mock", file=sys.stderr)
        raise SystemExit(2)


def cmd_premortem(args: argparse.Namespace) -> int:
    _require_credentials_or_mock(args.provider)
    from engine.pipeline import run_premortem

    run = run_premortem(
        repo=args.repo, base=args.base, head=args.head, with_refs=args.with_refs,
        fix=args.fix, provider_name=args.provider,
    )
    print(f"run_id={run.run_id} findings.defeated={len(run.findings['defeated'])} "
          f"findings.undefended={len(run.findings['undefended'])}")
    return 0


def cmd_postmortem(args: argparse.Namespace) -> int:
    _require_credentials_or_mock(args.provider)
    from engine.pipeline import run_postmortem

    run = run_postmortem(repo=args.repo, incident_path=args.incident, ref=args.ref, provider_name=args.provider)
    print(f"run_id={run.run_id} findings.defeated={len(run.findings['defeated'])}")
    return 0


def cmd_standing(args: argparse.Namespace) -> int:
    _require_credentials_or_mock(args.provider)
    from engine.pipeline import run_standing

    run = run_standing(repo=args.repo, ref=args.ref, provider_name=args.provider)
    print(f"run_id={run.run_id} findings.undefended={len(run.findings['undefended'])}")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    _require_credentials_or_mock(args.provider)
    from engine.bench import run_bench

    path = run_bench(repo=args.repo, provider_name=args.provider)
    print(f"wrote {path}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    from engine.replay import replay_run

    replay_run(args.run)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from engine.server import app

    uvicorn.run(app, host="0.0.0.0", port=args.port)
    return 0


DISPATCH = {
    "premortem": cmd_premortem,
    "postmortem": cmd_postmortem,
    "standing": cmd_standing,
    "bench": cmd_bench,
    "replay": cmd_replay,
    "serve": cmd_serve,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return DISPATCH[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
