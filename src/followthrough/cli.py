"""Command-line entry point: `followthrough sweep --fixture | --live --repo owner/name`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .config import DEFAULT_LANG, LANGS, ROOT, load, t

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_PARTIAL = 3  # digest written, but the sweep stopped early (budget); the digest says so


def _lang_from_argv(argv: list[str]) -> str:
    for i, arg in enumerate(argv):
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
    return DEFAULT_LANG


def build_parser(lang: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="followthrough", description=t("cli.description", lang))
    parser.add_argument("--lang", choices=LANGS, default=DEFAULT_LANG, help=t("cli.lang_help", lang))
    parser.add_argument("--version", action="version", version=t("cli.version", lang, version=__version__))
    sub = parser.add_subparsers(dest="command")
    sweep = sub.add_parser("sweep", help=t("cli.sweep_help", lang), description=t("cli.sweep_help", lang))
    # SUPPRESS: a subcommand default would overwrite a --lang given before the subcommand.
    sweep.add_argument("--lang", choices=LANGS, default=argparse.SUPPRESS, help=t("cli.lang_help", lang))
    source = sweep.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", nargs="?", const="", metavar="PATH", help=t("cli.fixture_help", lang))
    source.add_argument("--live", action="store_true", help=t("cli.live_help", lang))
    sweep.add_argument("--repo", metavar="OWNER/NAME", help=t("cli.repo_help", lang))
    sweep.add_argument("--now", metavar="ISO", help=t("cli.now_help", lang))
    sweep.add_argument("--reader", choices=("states", "model"), help=t("cli.reader_help", lang))
    sweep.add_argument("--states", metavar="PATH", help=t("cli.states_help", lang))
    sweep.add_argument("--out", metavar="DIR", help=t("cli.out_help", lang))
    sweep.add_argument("--draft", action="store_true", help=t("cli.draft_help", lang))
    sweep.add_argument("--format", choices=("md", "json"), default="md", help=t("cli.format_help", lang))
    return parser


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _now(value: str | None, default: str | None) -> datetime:
    from .state import parse_ts

    if value or default:
        return parse_ts(value or default or "")
    return datetime.now(UTC)


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return EXIT_USAGE


def sweep(args: argparse.Namespace, lang: str) -> int:
    from . import digest, sweep as sw

    policy, models = load("policy"), load("models")
    reader = args.reader or ("model" if args.live else "states")
    extra: dict[str, object] = {}
    if args.live and reader == "states":
        return _fail(t("cli.states_live", lang))
    if (reader == "model" or args.draft) and not os.environ.get(models["key_env"]):
        return _fail(t("cli.key_missing", lang, env=models["key_env"]))
    if args.live:
        if not args.repo or args.repo.count("/") != 1:
            return _fail(t("cli.repo_required", lang))
        from .github import GitHub

        now = _now(args.now, None)
        client = GitHub(policy)
        owner, name = args.repo.split("/")
        snapshot = client.snapshot(owner, name, now)
        client.write_snapshot(snapshot, now)
        client.save_cache()
        methods = [m for m, _, _ in client.requests]
        extra["http"] = {"requests": len(methods), "non_get": sum(1 for m in methods if m != "GET")}
    else:
        snapshot = sw.load_json(_path(args.fixture or policy["sweep"]["fixture"]))
        fixture = snapshot.get("fixture", {})
        now = _now(args.now, fixture.get("now") or snapshot.get("taken_at"))
    if reader == "states":
        report = sw.read_with_states(snapshot, sw.load_json(_path(args.states or policy["sweep"]["fixture_states"])))
    else:
        report = sw.read_with_model(snapshot, now, ROOT)
        extra["reading"] = report.counts()
    rows = sw.decide_all(snapshot, report, now, policy)
    if args.draft:
        extra["drafts"] = sw.run_drafts(snapshot, rows, now, ROOT, policy, models)
    built = digest.build(snapshot["repo"], now, "live" if args.live else "fixture", reader, rows,
                         stopped=report.stopped, extra=extra)
    markdown = digest.render_md(built, lang, policy["digest"]["list_actions"])
    folder = digest.write(built, markdown, _path(args.out or policy["sweep"]["output_dir"]))
    print(json.dumps(built, ensure_ascii=False, indent=1) if args.format == "json" else markdown, end="")
    print(t("cli.written", lang, folder=folder), file=sys.stderr)
    return EXIT_PARTIAL if report.stopped else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    lang = _lang_from_argv(argv)
    if lang not in LANGS:
        lang = DEFAULT_LANG
    parser = build_parser(lang)
    args = parser.parse_args(argv)
    if args.command == "sweep":
        return sweep(args, lang)
    parser.print_help()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
