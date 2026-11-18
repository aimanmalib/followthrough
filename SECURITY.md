# Security

Follow-Through holds a model key and a GitHub token and can post one comment after a human approves it, so a bug in
how those are handled matters.

## Reporting a vulnerability

Please don't open a public issue. Use
[private vulnerability reporting](https://github.com/aimanmalib/followthrough/security/advisories/new). You should get a
first answer within 7 days.

## What the design promises

- The GitHub client (`src/followthrough/github.py`) sends `GET` requests only; any other method raises before a request is made.
- `post_comment` in `src/followthrough/post.py` is the only code that writes to GitHub. It checks the stop file, then the
  allow-list in `config/safety.toml`, then asks a human. No answer means no post.
- The replay server (`src/followthrough/replay.py`) forwards model requests only to the upstream in `config/replay.toml`
  and refuses GitHub hosts.
- Keys come from the environment. They are not written to disk, to logs, to telemetry or to prompts.

A way around any of these is a vulnerability. Reports about OpenMinion itself belong to the OpenMinion project.

## Supported versions

Only the latest release gets fixes.
