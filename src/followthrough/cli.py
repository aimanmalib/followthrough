"""Command-line entry point: `followthrough sweep --fixture | --live --repo owner/name`."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .config import DEFAULT_LANG, LANGS, ROOT, load, t

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_FAILED = 1  # doctor turn check or scheduling proof did not pass
EXIT_PARTIAL = 3  # digest written, but the sweep stopped early (money or time limit); the digest says so


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
    doctor = sub.add_parser("doctor", help=t("cli.doctor_help", lang), description=t("cli.doctor_help", lang))
    doctor.add_argument("--lang", choices=LANGS, default=argparse.SUPPRESS, help=t("cli.lang_help", lang))
    doctor.add_argument("--out", metavar="DIR", help=t("cli.out_help", lang))
    schedule = sub.add_parser("schedule", help=t("cli.schedule_help", lang),
                              description=t("cli.schedule_help", lang))
    schedule.add_argument("--lang", choices=LANGS, default=argparse.SUPPRESS, help=t("cli.lang_help", lang))
    schedule.add_argument("--daily", metavar="HH:MM", required=True, help=t("cli.daily_help", lang))
    schedule.add_argument("--repo", metavar="OWNER/NAME", default="OWNER/NAME", help=t("cli.repo_help", lang))
    schedule.add_argument("--out", metavar="DIR", help=t("cli.out_help", lang))
    post = sub.add_parser("post", help=t("cli.post_help", lang), description=t("cli.post_help", lang))
    post.add_argument("--lang", choices=LANGS, default=argparse.SUPPRESS, help=t("cli.lang_help", lang))
    post.add_argument("--repo", metavar="OWNER/NAME", required=True, help=t("cli.post_repo_help", lang))
    post.add_argument("--number", type=int, required=True, help=t("cli.post_number_help", lang))
    post.add_argument("--draft", metavar="PATH", required=True, help=t("cli.post_draft_help", lang))
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
    from . import digest, measure, sweep as sw, telemetry

    policy, models = load("policy"), load("models")
    started, started_clock = datetime.now(UTC), time.monotonic()
    requests: list[tuple[str, str, int]] | None = None
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
        requests = list(client.requests)
        extra["http"] = {"requests": len(requests), "non_get": sum(1 for m, _, _ in requests if m != "GET")}
    else:
        snapshot = sw.load_json(_path(args.fixture or policy["sweep"]["fixture"]))
        fixture = snapshot.get("fixture", {})
        now = _now(args.now, fixture.get("now") or snapshot.get("taken_at"))
    if reader == "states":
        report = sw.read_with_states(snapshot, sw.load_json(_path(args.states or policy["sweep"]["fixture_states"])))
    else:
        until = sw.deadline(started_clock, load("ops")["measure"]["max_minutes"],
                            float(models["profiles"]["reader"].get("timeout_s") or 0))
        report = sw.read_with_model(snapshot, now, ROOT, until=until)
        extra["reading"] = report.counts()
    rows = sw.decide_all(snapshot, report, now, policy)
    drafted: list[object] = []
    if args.draft:
        extra["drafts"], drafted = sw.run_drafts(snapshot, rows, now, ROOT, policy, models)
    built = digest.build(snapshot["repo"], now, "live" if args.live else "fixture", reader, rows,
                         stopped=report.stopped, extra=extra)
    markdown = digest.render_md(built, lang, policy["digest"]["list_actions"])
    folder = digest.write(built, markdown, _path(args.out or policy["sweep"]["output_dir"]))
    ops = load("ops")
    telemetry.write(folder, telemetry.build(report.session_id, now, report.outcomes, drafted,
                                            ops["telemetry"]["stat_keys"]), ops["telemetry"]["file"])
    limits = {"max_minutes": ops["measure"]["max_minutes"], "usd_max_per_sweep": load("budget")["usd_max_per_sweep"]}
    metrics = measure.build(repo=snapshot["repo"], mode=built["mode"], started=started, finished=datetime.now(UTC),
                            digest=built, outcomes=report.outcomes, reading=extra.get("reading"),
                            requests=requests, limits=limits)
    measure.write(folder, metrics, ops["measure"]["file"], requests, ops["measure"]["http_log"])
    print(json.dumps(built, ensure_ascii=False, indent=1) if args.format == "json" else markdown, end="")
    print(t("cli.written", lang, folder=folder), file=sys.stderr)
    return EXIT_PARTIAL if report.stopped else EXIT_OK


def _dated(args: argparse.Namespace) -> Path:
    policy = load("policy")
    return _path(args.out or policy["sweep"]["output_dir"]) / datetime.now(UTC).strftime("%Y-%m-%d")


def doctor(args: argparse.Namespace, lang: str) -> int:
    from . import agents, schedule, telemetry

    ops, models = load("ops"), load("models")
    report = schedule.doctor(ops, agents.write_agents_json(ROOT, models), models["key_env"])
    path = telemetry.write(_dated(args), report, ops["doctor"]["file"])
    for part in ("project_config", "turn_check"):
        row = report[part]
        print(t(f"ops.doctor_{part}", lang, status=row["status"], provider=row["provider"] or "-",
                ok=row["counts"].get("ok", 0), warn=row["counts"].get("warn", 0),
                fail=row["counts"].get("fail", 0)))
    print(t("ops.saved", lang, path=path), file=sys.stderr)
    return EXIT_OK if report["turn_check"]["status"] == "ok" else EXIT_FAILED


def schedule_cmd(args: argparse.Namespace, lang: str) -> int:
    from . import schedule, telemetry

    try:
        hour, minute = schedule.parse_daily(args.daily)
    except ValueError:
        return _fail(t("ops.bad_daily", lang, value=args.daily))
    ops = load("ops")
    report = schedule.schedule_proof(ops, hour, minute)
    report["cron_line"] = schedule.cron_line(ops, hour, minute, args.repo, ROOT)
    path = telemetry.write(_dated(args), report, ops["schedule"]["file"])
    run = report.get("run") or {}
    print(t("ops.schedule_result", lang, cron=report["cron"], tz=report["tz"], state=run.get("state") or "-",
            ok=report["ok"]))
    print(t("ops.cron_line", lang))
    print(report["cron_line"])
    print(t("ops.saved", lang, path=path), file=sys.stderr)
    return EXIT_OK if report["ok"] else EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    lang = _lang_from_argv(argv)
    if lang not in LANGS:
        lang = DEFAULT_LANG
    parser = build_parser(lang)
    args = parser.parse_args(argv)
    if args.command == "sweep":
        return sweep(args, lang)
    if args.command == "doctor":
        return doctor(args, lang)
    if args.command == "schedule":
        return schedule_cmd(args, lang)
    if args.command == "post":
        if args.repo.count("/") != 1:
            return _fail(t("cli.repo_required", lang))
        from . import approve

        return approve.run(args.repo, args.number, _path(args.draft), lang, ROOT)
    parser.print_help()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
