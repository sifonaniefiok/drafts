"""Writing statistics derived entirely from git history.

Drafts keeps no separate database of sessions: the repository already records
what changed and when. For every commit that touched a draft we compare the
draft's text before and after the commit and count the *inserted* words (see
:func:`drafts.diffing.words_added`). Those counts are added up per day, using
the commit's author date in the timezone it was recorded in.

Because commits happen on save and on exit, "words per day" reflects committed
work; text that is only autosaved shows up once it is committed. Restore
commits are skipped, since bringing back old text is not writing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from drafts.diffing import words_added
from drafts.names import is_draft_file
from drafts.text import count_words
from drafts.workspace import RESTORE_PREFIX, Workspace


@dataclass(frozen=True)
class Stats:
    drafts: int
    total_words: int  # words currently in all drafts
    days: list[tuple[date, int]]  # (day, words written), oldest first
    today_words: int
    current_streak: int  # consecutive writing days ending today (or yesterday)
    longest_streak: int
    total_written: int  # words written over the whole history


def words_written_by_day(workspace: Workspace) -> dict[date, int]:
    """Map each day to the number of words written in commits on that day."""
    changes: list[tuple[date, str, str]] = []  # (day, commit sha, file name)
    for commit in workspace.git.log():
        if commit.subject.startswith(RESTORE_PREFIX):
            continue  # bringing back old text is not writing new words
        for file_name in commit.files:
            if is_draft_file(file_name):
                changes.append((commit.date.date(), commit.sha, file_name))

    # Fetch every "before" and "after" text in one batch (one git process).
    specs = []
    for _, sha, file_name in changes:
        specs += [f"{sha}^:{file_name}", f"{sha}:{file_name}"]
    texts = workspace.git.cat_files(specs)

    per_day: dict[date, int] = defaultdict(int)
    for index, (day, _, _) in enumerate(changes):
        before, after = texts[2 * index], texts[2 * index + 1]
        per_day[day] += words_added(before or "", after or "")
    return dict(per_day)


def streaks(active_days: set[date], today: date) -> tuple[int, int]:
    """(current streak, longest streak) in days.

    The current streak still counts if you have not written yet *today* but did
    yesterday: the day is not over, so the streak is not broken yet.
    """
    longest = run = 0
    previous: date | None = None
    for day in sorted(active_days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day

    current = 0
    cursor = today if today in active_days else today - timedelta(days=1)
    while cursor in active_days:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


def compute_stats(workspace: Workspace, today: date, days: int = 14) -> Stats:
    """Collect everything ``drafts stats`` shows. ``today`` is injected for tests."""
    by_day = words_written_by_day(workspace)
    window = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    current, longest = streaks({d for d, n in by_day.items() if n > 0}, today)
    names = workspace.drafts()
    total_words = sum(
        count_words((workspace.root / n).read_text(encoding="utf-8", errors="replace"))
        for n in names
    )
    return Stats(
        drafts=len(names),
        total_words=total_words,
        days=[(day, by_day.get(day, 0)) for day in window],
        today_words=by_day.get(today, 0),
        current_streak=current,
        longest_streak=longest,
        total_written=sum(by_day.values()),
    )
