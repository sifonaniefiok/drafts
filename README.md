# Drafts

[![CI](https://github.com/sifonaniefiok/drafts/actions/workflows/ci.yml/badge.svg)](https://github.com/sifonaniefiok/drafts/actions/workflows/ci.yml)

A minimal writing environment for the terminal. Distraction-free, plain-text,
version-controlled.

`drafts write essay` opens a full-screen editor with nothing in it but your text
in a centered column and a one-line status bar you can hide. Every draft is a
plain `.md` or `.txt` file in a folder that is also a git repository, so your
saves become history you can browse, diff and restore from the command line.

## Philosophy

- **Plain text forever.** Drafts are ordinary files in `~/drafts`. No database,
  no export lock-in: open them in any editor, sync them with anything, read
  them in twenty years.
- **Git is the undo history.** Instead of inventing a versioning system, Drafts
  commits to a normal git repository. `drafts history`, `diff` and `restore`
  are friendly views over it, and every git tool you already know still works.
- **Nothing but the words.** The editor has one column of text and one quiet
  status line. No menus, no sidebars, no formatting toolbar.
- **History is never rewritten.** Restoring an old version adds a new commit.
  Nothing Drafts does deletes a commit.

## Install

Requires Python 3.10+ and `git` on your `PATH`. Tested on Linux and macOS.

```bash
git clone https://github.com/sifonaniefiok/drafts.git
cd drafts
pip install .            # or: pipx install .
drafts --version         # drafts 0.1.0
```

Dependencies: [Rich](https://github.com/Textualize/rich) for terminal output and
[prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) for the
editor. Git is called as a subprocess; there is no git library dependency.

## Demo

Real output from a fresh workspace. The text was typed in the editor over three
sessions (two ended with `Ctrl-S` then `Ctrl-Q`, one with `Ctrl-Q` then `y`).
The output was captured through a pipe, so it has no colours; in a terminal,
insertions are green and deletions red. Without colours, the word diff falls
back to the `{+added+}` / `[-removed-]` markers used by
`git diff --word-diff=plain`.

```console
$ drafts new "on attention"
Created on-attention (~/drafts/on-attention.md)
Start writing with: drafts write on-attention

$ drafts write on-attention   # type, Ctrl-S, Ctrl-Q
on-attention: 9 words (+9 this session), 1 commit (latest b9db495)

$ drafts list
Drafts in ~/drafts

  Name           Words   Last edited   Commits
 ──────────────────────────────────────────────
  notes              4   just now            1
  on-attention      26   just now            4

$ drafts diff on-attention
on-attention: f927a36 → working copy   +4 words  -0 words
[…] spend it as if it cost nothing, then wonder where it went.

{+The rest is noise.+}

$ drafts restore on-attention f927a36
Restored on-attention to f927a36 as new commit 85c23ce. Nothing was deleted from
history.

$ drafts history on-attention
History of on-attention

  Commit    Date               Words   Change   Message
 ──────────────────────────────────────────────────────────────────
  85c23ce   2026-10-01 20:16      22       -4   Restore to f927a36
  33d1b91   2026-10-01 20:16      26       +4   Edit (+4 words)
  f927a36   2026-10-01 20:16      22      +13   Edit (+13 words)
  b9db495   2026-10-01 20:16       9       +9   Edit (+9 words)
  b8d8b7e   2026-10-01 20:15       0       +0   Create (0 words)

$ drafts stats --days 7
2 drafts · 26 words in total · 30 written today · streak 1 day (longest 1)
Words written, last 7 days

  Day          Words
 ─────────────────────────────────────────────────────
  Fri 25 Sep       ·
  Sat 26 Sep       ·
  Sun 27 Sep       ·
  Mon 28 Sep       ·
  Tue 29 Sep       ·
  Wed 30 Sep       ·
  Thu 01 Oct      30   ██████████████████████████████

$ drafts export on-attention --format txt
                              On Attention

Attention is the rarest form of generosity. We spend it as if it cost
nothing, then wonder where it went.

$ drafts sync
No remote configured, so there is nothing to sync with.
Add one with: git -C ~/drafts remote add origin <url>
```

A sketch of the editor screen (`drafts write on-attention --goal 500`): the text
column is centered, and the status line sits at the bottom of the terminal.

```text

          # On Attention

          Attention is the rarest form of generosity. We spend it as if it
          cost nothing, then wonder where it went.



 on-attention  ·  22 words  ·  +13 this session  ·  goal 13/500 (3%)  ·  20:16  ·  saved
```

## The editor

```bash
drafts write NAME [--goal WORDS] [--width 72] [--typewriter] [--no-status]
                  [--autosave SECONDS] [--commit-interval SECONDS]
```

`NAME` is created if it does not exist (nothing is written until you type and
save). The text column is `--width` characters wide (default 72), centered and
soft-wrapped; it shrinks if the terminal is narrower.

The status line shows: draft name · word count · net words this session ·
goal progress (with `--goal`) · clock · `saved` or `● unsaved`, plus short
messages such as `saved · committed 33d1b91` that fade after a few seconds.

`--typewriter` keeps about half a screen of space above and below the cursor
line, so the line you are writing stays near the middle of the screen. (A
single paragraph taller than half the screen scrolls normally.)

### Keybindings

| Key | Action |
| --- | --- |
| `Ctrl-S` | Save to disk and commit (see [how versioning works](#how-versioning-works)) |
| `Ctrl-Q` or `Ctrl-X` | Quit. With unsaved changes it asks: `y` save and quit, `n` quit without saving, `c` or `Esc` keep writing |
| `Ctrl-T` | Show / hide the status line |
| `Tab` | Insert four spaces |

All other keys use prompt_toolkit's default Emacs-style bindings: arrows,
`Home`/`End`, `Ctrl-A`/`Ctrl-E` (line start/end), `Ctrl-K` (delete to end of
line), `Ctrl-W` (delete previous word) and `Ctrl-_` (undo).

`Ctrl-S` and `Ctrl-Q` work even in terminals that use them for flow control,
because prompt_toolkit puts the terminal in raw mode.

## Commands

All commands accept `--dir PATH` (before or after the command name) to use a
workspace other than the default.

| Command | What it does |
| --- | --- |
| `drafts write NAME` | Open the distraction-free editor (above). |
| `drafts new NAME` | Create an empty draft and commit it. Refuses to overwrite. |
| `drafts list` | Table of drafts: name, words, last edited, number of commits. |
| `drafts history NAME [-n N]` | Committed versions of a draft: commit, date, words, change in words, message. Uncommitted changes appear as a `(working)` row. |
| `drafts diff NAME [REV] [--lines]` | Word-level diff between `REV` and the file on disk. Without `REV`: against the last commit if there are uncommitted changes, otherwise what the last commit changed. `--lines` shows a unified line diff instead. |
| `drafts restore NAME REV` | Bring back the version from `REV` as a **new** commit. |
| `drafts stats [--days 14]` | Number of drafts, total words, words written per day for the last N days, current and longest streak. |
| `drafts export NAME [--format html\|txt] [-o FILE] [--width 72]` | Export to a standalone HTML page (default) or formatted plain text. Writes to stdout unless `-o` is given. |
| `drafts snapshot` | Commit any drafts changed outside Drafts (for example in another editor). |
| `drafts sync` | If the workspace has a git remote: snapshot, `git fetch`, `git pull --rebase` (when the remote branch exists), then `git push`. Without a remote it explains how to add one and exits with status 1. |

`REV` is anything git understands: a short hash from `drafts history`, `HEAD~2`,
a tag or a branch.

**Names.** `"My Essay"` becomes `My-Essay.md`: whitespace becomes `-`,
characters other than letters, digits, `_`, `-` and `.` are dropped, and `.md`
is added unless the name ends in `.md` or `.txt`. Names containing `/`, `\` or
`..`, or starting with `.`, are rejected, so a draft can never be a hidden file
or live outside the workspace. `essay` and `essay.md` are the same draft.

**Word counts.** A word is a whitespace-separated token containing a letter or
digit, so Markdown markers (`#`, `-`, `>`, `1.`, `---`) don't count;
`**bold**`, `don't` and `well-known` are one word each; em and en dashes
separate words; only the text of a link counts, not its URL; fenced code blocks
are skipped; each Chinese or Japanese character counts as one word.

**Export.** HTML export uses a small built-in Markdown converter (headings,
paragraphs, emphasis, strong, strikethrough, inline and fenced code, links,
images, one-level lists, blockquotes, rules). All text is HTML-escaped first,
so raw HTML in a draft is shown rather than executed, and only `http`, `https`,
`mailto` and relative URLs are kept in links and images. Nested lists, tables
and footnotes are not supported. `.txt` drafts are exported as escaped
paragraphs. Text export renders Markdown with Rich, without colour codes.

## How versioning works

Saving to disk and committing are deliberately separate:

| Event | Writes the file | Creates a commit |
| --- | --- | --- |
| Autosave (every `--autosave` seconds, default 30, when there are changes) | yes | **no** |
| `Ctrl-S` | yes | yes, unless this session committed less than `--commit-interval` seconds ago (default 60); then the commit is *pending* |
| Quit (`y`, or no unsaved changes) | yes | yes, if the file differs from the last commit |
| Quit with `n` | no: keystrokes since the last save or autosave are discarded | yes, for whatever is already on disk |

- **Debouncing.** Autosaves and rapid `Ctrl-S` presses never produce a burst of
  commits. Their changes go into the next commit, which happens at the latest
  when you quit.
- **No empty commits.** A commit is only made when the file differs from the
  last commit. Pressing `Ctrl-S` twice in a row, or quitting without changes,
  makes no commit.
- **Crash safety.** Files are written atomically (temporary file, then rename).
  If the editor is killed, autosaved text is on disk; the next `drafts write` of
  that draft first commits it as a `Snapshot` commit, so each session's commits
  contain only that session's work.
- **Commit messages** describe the change in words: `Create essay.md (0 words)`,
  `Edit essay.md (+120 words)`, `Snapshot essay.md (+3 words)`,
  `Restore essay.md to f927a36`. Only the draft being saved is committed.
- **Restore** reads the old text with `git show`, commits any uncommitted edits
  first (as a `Snapshot`, so they are not lost), writes the old text and commits
  it as `Restore <file> to <rev>`. The versions in between stay in history, so a
  restore can itself be undone with another restore.
- **Statistics** come from history, not a separate database. For each commit,
  the draft before and after is compared with a word diff and the *inserted*
  words are summed per day (by the commit's author date). Rewriting ten words
  counts as ten words written even if the length didn't change. Restore commits
  are not counted. The current streak counts consecutive days with writing up to
  today, or up to yesterday if you haven't written yet today.

## Where files live

- Workspace: `--dir PATH`, else `$DRAFTS_DIR`, else `~/drafts`. The folder and a
  git repository (branch `main`) are created on first use. If the folder is
  inside another git repository, Drafts still creates its own repository there
  and never commits to the outer one.
- Drafts: `*.md` and `*.txt` files directly in the workspace folder.
- Git identity: your normal git `user.name` / `user.email`. Only if none is
  configured, Drafts sets `Drafts <drafts@localhost>` in the workspace
  repository's local config so commits never fail. Your global git config is
  never changed.
- To back up or sync, add a remote (`git -C ~/drafts remote add origin <url>`)
  and run `drafts sync`.

## Architecture

The editor logic is kept apart from the terminal UI, so almost everything is
tested with plain function calls.

| File | Responsibility |
| --- | --- |
| `src/drafts/cli.py` | `argparse` commands and Rich output; `main(argv)` is the entry point. |
| `src/drafts/editor.py` | prompt_toolkit UI: layout, keybindings, autosave timer. The only module that imports prompt_toolkit. |
| `src/drafts/session.py` | `WritingSession`: buffer state, dirty tracking, word and goal counts, status-line text and the commit policy. Takes an injectable clock. |
| `src/drafts/workspace.py` | `Workspace`: where drafts live, atomic writes, commit / snapshot / history / restore by draft name. |
| `src/drafts/gitrepo.py` | Small wrapper around the `git` CLI via `subprocess` (`init`, `commit`, `log`, batched `cat-file`). |
| `src/drafts/text.py` | Word counting rules. |
| `src/drafts/diffing.py` | Word-level and line diffs (`difflib`) and their Rich rendering. |
| `src/drafts/stats.py` | Words written per day and streaks, derived from git history. |
| `src/drafts/export.py` | Safe Markdown → HTML converter and Markdown → plain text. |
| `src/drafts/names.py` | Draft name sanitization. |
| `tests/` | pytest suite (see below). |

## Development

```bash
pip install -e ".[dev]"
ruff check .          # lint
pytest                # run the tests
```

The tests run real git commands in temporary directories, with an isolated
`HOME` and no global or system git config, so they never touch your `~/drafts`
or git settings. They cover workspace and repository creation, the identity
fallback, save/autosave/commit debouncing with a fake clock, the no-empty-commit
rule, history and restore round trips, word and line diffs, word-count edge
cases (Unicode, CJK, Markdown, code), per-day statistics from commits made at
fixed dates (`GIT_AUTHOR_DATE` / `GIT_COMMITTER_DATE`), name sanitization, HTML
export safety, every CLI command through `main(argv)` (including `sync` against
a local bare repository), and smoke tests that run the real prompt_toolkit
editor with piped keystrokes (typing, `Ctrl-S`, `Ctrl-Q`, the quit prompt).

CI runs lint and tests on Ubuntu and macOS with Python 3.10, 3.11 and 3.12.

## License

[MIT](LICENSE) © 2026 Sifon Aniefiok
