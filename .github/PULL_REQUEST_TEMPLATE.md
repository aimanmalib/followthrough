## What and why

## How I tested it

- [ ] `uv run pytest -q` (offline, no key)
- [ ] `demo/run.sh` (if this touches the reader, the drafter, the replay or the demo image)
- [ ] If this touches the write path (`post.py`) or the GitHub client: a test that fails without this change
- [ ] User-facing text added to both `locales/en.toml` and `locales/ms.toml`
