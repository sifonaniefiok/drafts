"""Command-line interface: argument parsing and Rich output for every command.

Each ``cmd_*`` function receives the parsed arguments, an opened
:class:`~drafts.workspace.Workspace` and a Rich console, and returns an exit
code. ``main(argv)`` is the console-script entry point and is also what the
tests call, so the whole CLI can be exercised without spawning processes.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from drafts import __version__
from drafts.diffing import (
    line_diff,
    render_line_diff,
    render_word_diff,
    summarize,
    word_diff,
)
from drafts.export import to_html, to_text
from drafts.gitrepo import GitError
from drafts.names import InvalidNameError, display_name
from drafts.session import DEFAULT_AUTOSAVE_INTERVAL, DEFAULT_COMMIT_INTERVAL
from drafts.stats import compute_stats
from drafts.workspace import DraftNotFoundError, Workspace

#: Replaced in tests to pin "today" for ``drafts stats``.
today: Callable[[], date] = date.today


# --------------------------------------------------------------------- helpers


def relative_time(moment: datetime, now: datetime | None = None) -> str:
    """Human-friendly age of ``moment``: "just now", "5 min ago", "2024-03-01"."""
    now = now or datetime.now()
    seconds = (now - moment).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = (now.date() - moment.date()).days
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    return moment.strftime("%Y-%m-%d")


def pretty_path(path: Path) -> str:
    """Show paths under the home directory as ``~/...`` to keep output short."""
    try:
        return "~/" + str(path.relative_to(Path.home().resolve()))
    except ValueError:
        return str(path)


def _short_label(workspace: Workspace, name: str) -> str:
    return display_name(workspace.path_for(name).name)


# -------------------------------------------------------------------- commands


def cmd_write(args: argparse.Namespace, ws: Workspace, console: Console) -> int:
    # Imported here so commands that never open the editor start faster.
    from drafts.editor import Editor, EditorOptions
    from drafts.session import WritingSession

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        console.print("[red]drafts write needs an interactive terminal.[/]")
        return 1
    session = WritingSession(
        ws,
        args.name,
        goal=args.goal,
        autosave_interval=args.autosave,
        commit_interval=args.commit_interval,
    )
    options = EditorOptions(
        width=args.width, show_status=not args.no_status, typewriter=args.typewriter
    )
    result = Editor(session, options).run()
    label = display_name(session.file_name)
    summary = f"{label}: {session.word_count:,} words ({session.session_words:+,} this session)"
    commits = len(session.commits)
    if commits:
        plural = "s" if commits != 1 else ""
        summary += f", {commits} commit{plural} (latest {session.commits[-1][:7]})"
    else:
        summary += ", nothing new to commit"
    if not result.saved:
        summary += " — unsaved edits discarded"
    console.print(summary)
    return 0


def cmd_new(args: argparse.Namespace, ws: Workspace, console: Console) -> int:
    path = ws.path_for(args.name)
    label = display_name(path.name)
    if path.exists():
        console.print(f"[red]A draft called {label!r} already exists.[/]")
        return 1
    ws.write(path.name, "")
    ws.commit(path.name, ws.commit_message(path.name))
    console.print(f"Created [bold]{label}[/] ({pretty_path(path)})", soft_wrap=True)
    console.print(f"Start writing with: drafts write {label}")
    return 0


def cmd_list(args: argparse.Namespace, ws: Workspace, console: Console) -> int:
    infos = ws.list_drafts()
    if not infos:
        console.print(
            f"No drafts yet in {pretty_path(ws.root)}. Start one with: drafts write NAME",
            soft_wrap=True,
        )
        return 0
    table = Table(
        box=box.SIMPLE_HEAD, title=f"Drafts in {pretty_path(ws.root)}", title_justify="left"
    )
    table.add_column("Name", style="bold")
    table.add_column("Words", justify="right")
    table.add_column("Last edited")
    table.add_column("Commits", justify="right")
    for info in infos:
        table.add_row(info.name, f"{info.words:,}", relative_time(info.modified), str(info.commits))
    console.print(table)
    return 0


def cmd_history(args: argparse.Namespace, ws: Workspace, console: Console) -> int:
    file_name = ws.path_for(args.name).name
    label = display_name(file_name)
    versions = ws.history(args.name, limit=args.limit)
    if not versions:
        console.print(f"[red]No history for {label!r}.[/] Is the name right? Try: drafts list")
        return 1
    table = Table(box=box.SIMPLE_HEAD, title=f"History of {label}", title_justify="left")
    table.add_column("Commit", style="yellow")
    table.add_column("Date")
    table.add_column("Words", justify="right")
    table.add_column("Change", justify="right")
    table.add_column("Message")
    if ws.exists(args.name) and ws.is_dirty(args.name):
        table.add_row("(working)", "now", "", "", "[italic]uncommitted changes[/]")
    for version in versions:
        delta = version.delta
        style = "green" if delta > 0 else "red" if delta < 0 else "dim"
        table.add_row(
            version.commit.short_sha,
            version.commit.date.strftime("%Y-%m-%d %H:%M"),
            f"{version.words:,}",
            Text(f"{delta:+,}", style=style),
            # The file name is in every subject; in a per-draft view it is noise.
            Text(version.commit.subject.replace(f" {file_name}", "", 1)),
        )
    console.print(table)
    return 0


def cmd_diff(args: argparse.Namespace, ws: Workspace, console: Console) -> int:
    label = _short_label(ws, args.name)
    new_text = ws.read(args.name)
    if args.rev:
        old_text = ws.text_at(args.name, args.rev)
        old_label = args.rev
    else:
        # Default: what changed since the last commit, or, if there are no
        # uncommitted changes, what the last commit changed.
        versions = ws.history(args.name, limit=2)
        index = 0 if ws.is_dirty(args.name) else 1
        if len(versions) > index:
            old_label = versions[index].commit.short_sha
            old_text = ws.text_at(args.name, versions[index].commit.sha)
        else:
            old_label, old_text = "(empty)", ""
    new_label = "working copy"
    if old_text == new_text:
        console.print(f"No differences between {escape(old_label)} and the {new_label} of {label}.")
        return 0
    if args.lines:
        console.print(render_line_diff(line_diff(old_text, new_text, old_label, new_label)))
        return 0
    chunks = word_diff(old_text, new_text)
    added, removed = summarize(chunks)
    console.print(
        f"[bold]{label}[/]: {escape(old_label)} → {new_label}   "
        f"[green]+{added} words[/]  [red]-{removed} words[/]"
    )
    # Without colour (e.g. piped to a file) fall back to git-style markers.
    console.print(render_word_diff(chunks, markers=console.color_system is None))
    return 0


def cmd_restore(args: argparse.Namespace, ws: Workspace, console: Console) -> int:
    label = _short_label(ws, args.name)
    sha = ws.restore(args.name, args.rev)
    if sha is None:
        console.print(f"{label} already matches {escape(args.rev)}; nothing to restore.")
    else:
        console.print(
            f"Restored [bold]{label}[/] to {escape(args.rev)} as new commit [yellow]{sha[:7]}[/]. "
            "Nothing was deleted from history."
        )
    return 0


def cmd_stats(args: argparse.Namespace, ws: Workspace, console: Console) -> int:
    stats = compute_stats(ws, today=today(), days=args.days)
    streak_days = "day" if stats.current_streak == 1 else "days"
    console.print(
        f"[bold]{stats.drafts}[/] drafts · [bold]{stats.total_words:,}[/] words in total · "
        f"[bold]{stats.today_words:,}[/] written today · "
        f"streak [bold]{stats.current_streak}[/] {streak_days} "
        f"(longest {stats.longest_streak})"
    )
    table = Table(
        box=box.SIMPLE_HEAD, title=f"Words written, last {args.days} days", title_justify="left"
    )
    table.add_column("Day")
    table.add_column("Words", justify="right")
    table.add_column("", no_wrap=True)
    peak = max((n for _, n in stats.days), default=0) or 1
    for day, count in stats.days:
        bar = "█" * round(30 * count / peak) if count else ""
        table.add_row(day.strftime("%a %d %b"), f"{count:,}" if count else "·", Text(bar, "green"))
    console.print(table)
    return 0


def cmd_export(args: argparse.Namespace, ws: Workspace, console: Console) -> int:
    path = ws.path_for(args.name)
    text = ws.read(args.name)
    label = display_name(path.name)
    is_markdown = path.suffix == ".md"
    if args.format == "html":
        output = to_html(text, title=label, markdown=is_markdown)
    else:
        output = to_text(text, width=args.width) if is_markdown else text
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        console.print(f"Exported {label} to {args.output}")
    else:
        sys.stdout.write(output)
    return 0


def cmd_snapshot(args: argparse.Namespace, ws: Workspace, console: Console) -> int:
    made = 0
    for file_name in ws.drafts():
        sha = ws.snapshot(file_name)
        if sha:
            made += 1
            console.print(f"Committed {display_name(file_name)} [yellow]{sha[:7]}[/]")
    if not made:
        console.print("Nothing to commit; every draft matches its last commit.")
    return 0


def cmd_sync(args: argparse.Namespace, ws: Workspace, console: Console) -> int:
    remotes = ws.git.remotes()
    if not remotes:
        console.print(
            "No remote configured, so there is nothing to sync with.\n"
            f"Add one with: git -C {pretty_path(ws.root)} remote add origin <url>",
            soft_wrap=True,
        )
        return 1
    remote = "origin" if "origin" in remotes else remotes[0]
    branch = ws.git.current_branch()
    for file_name in ws.drafts():  # include edits made outside Drafts
        ws.snapshot(file_name)
    console.print(f"Syncing [bold]{branch}[/] with [bold]{remote}[/]…")
    ws.git.run("fetch", remote)
    remote_ref = f"refs/remotes/{remote}/{branch}"
    if ws.git.run("rev-parse", "--verify", "--quiet", remote_ref, check=False).returncode == 0:
        ws.git.run("pull", "--rebase", remote, branch)
    ws.git.run("push", "--set-upstream", remote, branch)
    console.print("Done.")
    return 0


# ---------------------------------------------------------------------- parser


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive number, got {value}")
    return number


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive number, got {value}")
    return number


def build_parser() -> argparse.ArgumentParser:
    # --dir is accepted both before and after the command name. Sub-parsers use
    # SUPPRESS so that, when omitted after the command, they don't overwrite a
    # value given before it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--dir",
        default=argparse.SUPPRESS,
        metavar="PATH",
        help="workspace directory (default: $DRAFTS_DIR or ~/drafts)",
    )

    parser = argparse.ArgumentParser(
        prog="drafts",
        description="A minimal writing environment for the terminal. "
        "Plain-text drafts, versioned with git.",
    )
    parser.add_argument("--version", action="version", version=f"drafts {__version__}")
    parser.add_argument(
        "--dir",
        default=None,
        metavar="PATH",
        help="workspace directory (default: $DRAFTS_DIR or ~/drafts)",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    def add(name: str, help: str, func: Callable[..., int]) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help, description=help, parents=[common])
        p.set_defaults(func=func)
        return p

    p = add("write", "open a draft in the distraction-free editor", cmd_write)
    p.add_argument("name")
    p.add_argument("--goal", type=positive_int, metavar="WORDS", help="word goal for this session")
    p.add_argument("--width", type=positive_int, default=72, help="text column width (default 72)")
    p.add_argument(
        "--autosave",
        type=positive_float,
        default=DEFAULT_AUTOSAVE_INTERVAL,
        metavar="SECONDS",
        help="write to disk this often (default 30)",
    )
    p.add_argument(
        "--commit-interval",
        type=positive_float,
        default=DEFAULT_COMMIT_INTERVAL,
        metavar="SECONDS",
        help="minimum time between Ctrl-S commits (default 60)",
    )
    p.add_argument(
        "--typewriter",
        action="store_true",
        help="keep the cursor line near the middle of the screen",
    )
    p.add_argument("--no-status", action="store_true", help="start with the status line hidden")

    p = add("new", "create an empty draft", cmd_new)
    p.add_argument("name")

    add("list", "list drafts with word counts", cmd_list)

    p = add("history", "show the committed versions of a draft", cmd_history)
    p.add_argument("name")
    p.add_argument("-n", "--limit", type=positive_int, default=None, help="show at most N versions")

    p = add("diff", "show what changed in a draft (word-level by default)", cmd_diff)
    p.add_argument("name")
    p.add_argument("rev", nargs="?", help="compare against this commit (default: see README)")
    p.add_argument("--lines", action="store_true", help="show a line diff instead")

    p = add("restore", "bring back an old version as a new commit", cmd_restore)
    p.add_argument("name")
    p.add_argument("rev", help="commit to restore from (see drafts history)")

    p = add("stats", "words written per day and your streak", cmd_stats)
    p.add_argument(
        "--days", type=positive_int, default=14, help="number of days to show (default 14)"
    )

    p = add("export", "export a draft to HTML or formatted text", cmd_export)
    p.add_argument("name")
    p.add_argument("--format", choices=["html", "txt"], default="html")
    p.add_argument("-o", "--output", metavar="FILE", help="write here instead of stdout")
    p.add_argument("--width", type=positive_int, default=72, help="text width for txt (default 72)")

    add("snapshot", "commit drafts edited outside Drafts", cmd_snapshot)
    add("sync", "pull --rebase and push, if a git remote is configured", cmd_sync)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``drafts`` command. Returns the process exit code."""
    args = build_parser().parse_args(argv)
    console = Console(highlight=False)
    errors = Console(stderr=True, highlight=False)
    try:
        workspace = Workspace.open(args.dir)
        return args.func(args, workspace, console)
    except (InvalidNameError, DraftNotFoundError) as exc:
        errors.print(f"[red]error:[/] {exc}")
        return 1
    except GitError as exc:
        errors.print(f"[red]git error:[/] {exc}")
        return 2
    except KeyboardInterrupt:
        return 130
