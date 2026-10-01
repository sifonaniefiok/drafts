from datetime import date, timedelta

from drafts.stats import compute_stats, streaks, words_written_by_day


def test_words_per_day_from_commits_at_controlled_dates(ws, commit_on) -> None:
    commit_on(ws, "essay", "one two three", "2026-03-01T09:00:00+00:00")
    commit_on(ws, "essay", "one two three four five", "2026-03-01T21:00:00+00:00")
    commit_on(ws, "poem", "roses are red", "2026-03-02T08:00:00+00:00")
    # A rewrite: same length, two words replaced -> two words written.
    commit_on(ws, "essay", "one two THREE FOUR five", "2026-03-04T12:00:00+00:00")

    assert words_written_by_day(ws) == {
        date(2026, 3, 1): 5,
        date(2026, 3, 2): 3,
        date(2026, 3, 4): 2,
    }


def test_compute_stats_window_totals_and_streak(ws, commit_on) -> None:
    for day, text in [(1, "a b"), (2, "a b c d"), (3, "a b c d e f"), (5, "a b c d e f g")]:
        commit_on(ws, "essay", text, f"2026-03-0{day}T10:00:00+00:00")

    stats = compute_stats(ws, today=date(2026, 3, 5), days=7)
    assert [d for d, _ in stats.days] == [date(2026, 2, 27) + timedelta(days=i) for i in range(7)]
    assert [n for _, n in stats.days] == [0, 0, 2, 2, 2, 0, 1]
    assert dict(stats.days)[date(2026, 3, 2)] == 2
    assert stats.today_words == 1
    assert stats.total_words == 7
    assert stats.total_written == 7
    assert stats.current_streak == 1  # 4 March was skipped
    assert stats.longest_streak == 3
    assert stats.drafts == 1


def test_streak_survives_until_the_day_is_over() -> None:
    active = {date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)}
    assert streaks(active, today=date(2026, 3, 3)) == (3, 3)
    assert streaks(active, today=date(2026, 3, 4)) == (3, 3)  # not written yet today
    assert streaks(active, today=date(2026, 3, 5)) == (0, 3)  # a full day missed
    assert streaks(set(), today=date(2026, 3, 5)) == (0, 0)


def test_restores_do_not_count_as_writing(ws, commit_on, monkeypatch) -> None:
    first = commit_on(ws, "essay", "a b c d", "2026-03-01T10:00:00+00:00")
    commit_on(ws, "essay", "x", "2026-03-02T10:00:00+00:00")
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2026-03-03T10:00:00+00:00")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-03-03T10:00:00+00:00")
    assert ws.restore("essay", first) is not None
    assert date(2026, 3, 3) not in words_written_by_day(ws)
