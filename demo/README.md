# Demo guide

The demo goes from sweep to digest to draft to approval in under five minutes. Steps 1 to 3 need Docker only:
no key, no account, no network while the demo runs. Step 4 posts a real comment, so it needs your own keys and
a repository you own.

## 1. Run the sweep (about 1 minute)

```sh
git clone https://github.com/aimanmalib/followthrough && cd followthrough
demo/run.sh
```

`demo/run.sh` builds a small image, runs `followthrough replay --serve -- sweep --fixture --reader model --draft`
in a container with no network and a read-only root, then removes the image. Every model answer comes from
`fixtures/recorded/`, recorded once from the real API. If a request was never recorded, the run fails and prints
a diff; it never falls through to the API.

Measured times are in [`docs/TEST-RESULTS.md`](../docs/TEST-RESULTS.md), "Key-free demo" and "Release".

## 2. Read the digest (about 1 minute)

The digest prints first. Look for:

- **Counts by action.** Each changed thread gets exactly one: follow-up due, take-over allowed, maintainer reply
  pending, ready to verify or no action.
- **One line per thread** with its number and a neutral sentence that names the date the rules worked out, for
  example "maintainer request unanswered since ..." or "take-over allowed from ...".
- **Quote check.** The last line counts readings the quote check rejected and threads that could not be read. A
  date the model relies on must be quoted word for word from a real comment; if not, the thread gets no reminder.
- **The model's real faults.** The recording keeps them: in the recorded run the quote check rejected 2 readings
  and 1 thread could not be read. The demo shows them; it does not hide them.

For the Malay digest, run `demo/run.sh replay --serve -- sweep --fixture --reader model --lang ms`.

## 3. Read the drafts (about 1 minute)

After the digest, the demo prints every draft it saved (`--- drafts/<number>.md ---`). Check that each one:

- is at most 120 words, neutral, and has no `@` mentions;
- names the date from the digest, and the take-over date when the thread allows one;
- follows the steps in the repository's own contributing guide.

Nothing is posted in the demo. A draft waits for a person.

## 4. Approve or deny (about 2 minutes, your own repository)

Posting is a separate command, and it is the only write path:

```sh
uv sync
export ANTHROPIC_API_KEY=...            # model key
export GITHUB_TOKEN=$(gh auth token)    # needs write access to your own repository
uv run followthrough sweep --live --repo you/your-repo --draft
uv run followthrough post --repo you/your-repo --number 42 --draft out/<date>/drafts/42.md
```

First add `you/your-repo` to `allow_post_repos` in `config/safety.toml`. `post` checks three things, in this order:

1. **Stop file.** If `state/STOP` exists, or the file named by the stop variable in `config/safety.toml`, it exits
   with code 5 before anything else.
2. **Allow-list.** A repository that is not in `allow_post_repos` is refused before the model and before any
   request to GitHub.
3. **Approval.** It shows the exact body and asks. Only `allow_once` posts, and then exactly one comment with
   that body. Anything else, including end of input, means deny.

The measured run on the project's own sandbox repository (deny: 0 comments, `allow_once`: exactly 1, stop file:
exit 5) is in [`docs/TEST-RESULTS.md`](../docs/TEST-RESULTS.md), "Sandbox approval demo".

## Without Docker

The same sample runs on saved readings with no model (digest only; drafts need the model):

```sh
uv sync
uv run followthrough sweep --fixture
```

## If something goes wrong

| Symptom | Cause | What to do |
|---|---|---|
| `demo: Docker is required` (exit 2) | Docker is not installed or not on `PATH` | Install Docker, or use "Without Docker" |
| Exit 4 with a diff | A request did not match any recording | Open an issue with the diff; the recording may need to be refreshed |
| `post` refuses the repository | It is not in `allow_post_repos` | Add your own repository there |
| `post` exits 5 | A stop file exists | Remove `state/STOP` when you mean to post again |

Set `FOLLOWTHROUGH_DEMO_KEEP=1` to keep the image for a second run.
