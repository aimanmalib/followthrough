"""Command-line entry point. Subcommands are added as each part is built."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import DEFAULT_LANG, LANGS, t


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
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    lang = _lang_from_argv(argv)
    if lang not in LANGS:
        lang = DEFAULT_LANG
    build_parser(lang).parse_args(argv)
    print(t("cli.not_ready", lang))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
