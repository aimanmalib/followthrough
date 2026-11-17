# Follow-Through

An agent for open-source maintainers, built on the OpenMinion SDK for **Cortensor Hackathon #5**.

Every day it reads the issue and pull request threads that changed, works out who is waiting on whom,
applies the follow-up windows from the repo's own CONTRIBUTING guide, and drafts a short follow-up.
A human approves every comment before it is posted. A memory ledger stops it from sending the same
reminder twice. It never posts to a repo that is not on its allow-list.

**Status:** early build. Nothing below is measured yet; numbers will appear in
[`docs/TEST-RESULTS.md`](docs/TEST-RESULTS.md) as they are produced.

## Planned shape

- Read-only GitHub access (GET requests only), with ETag caching.
- One OpenMinion subagent per changed thread, returning a typed thread state.
- Every quote the model returns must exist word for word in a real comment; otherwise the thread is marked unclear.
- Deterministic rules for the follow-up windows. All windows, labels, models, prices and limits live in `config/*.toml`.
- One write path (`post_comment`): stop file first, then allow-list, then human approval.
- Output in English or Malay (`--lang en|ms`).

## Development

```sh
uv sync
uv run pytest -q
```

Decisions are recorded in [`docs/decisions/`](docs/decisions/), each with a rollback note.

## AI disclosure

This project is an entry to Cortensor Hackathon #5. The code and documentation are written with
Claude Code (Anthropic), directed and reviewed by the author. The narration in the demo video uses an
ElevenLabs clone of the author's own voice. The agent itself calls Anthropic models through OpenMinion
at run time, within the spend limits in `config/budget.toml`.

## License

MIT. See [`LICENSE`](LICENSE).
