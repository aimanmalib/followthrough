# Contributing

Thanks for helping. Follow-Through can post a comment on someone's issue, so changes to the write path and the
GitHub client get extra scrutiny.

## Set up

Python 3.12 and [uv](https://docs.astral.sh/uv/). Docker is needed only for the key-free demo.

```sh
uv sync
uv run pytest -q                              # offline: no key, no network
uv run followthrough sweep --fixture --lang en
demo/run.sh                                   # replayed model answers in Docker
```

## Before you open a pull request

- Run `uv run pytest -q`; CI runs the same tests, the fixture sweep in both languages and the demo.
- Tests make no network requests. The model is a local fake server or a recorded replay; GitHub is a fake `urlopen`.
- `src/followthrough/github.py` stays `GET` only, and `post.py` stays the only code that writes to GitHub. A change to
  either needs a test that fails without your change.
- Values that someone may want to change (windows, labels, models, prices, limits, allow-list) go in `config/*.toml`,
  not in the code.
- User-facing text goes in `locales/en.toml` and `locales/ms.toml`, with the same keys.
- Modules stay under 400 lines.
- A design change gets a short record in `docs/decisions/`, with a rollback note.
- Fixtures and recordings hold invented text only. Do not commit snapshots, readings or drafts from a real repository.
- One topic per pull request; describe how you tested it.

## Reporting security issues

Please don't open a public issue. Use
[private vulnerability reporting](https://github.com/aimanmalib/followthrough/security/advisories/new).

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE) and that you follow
the [Code of Conduct](CODE_OF_CONDUCT.md).
