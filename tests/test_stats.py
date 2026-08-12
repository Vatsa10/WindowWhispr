from core.stats import (
    DAY_SECONDS,
    SessionRecord,
    StatsSummary,
    local_day,
    summary,
    wpm,
)

# A fixed "now": no clock in the tests.
NOW = 1_770_000_000
IST = -330  # minutes to add to local time to reach UTC


def rec(days_ago=0, words=10, duration_ms=10_000, at=None):
    ts = at if at is not None else NOW - days_ago * DAY_SECONDS
    return SessionRecord(ts_unix=ts, words=words, duration_ms=duration_ms)


def test_empty_history():
    assert summary([], IST, NOW) == StatsSummary()


def test_totals_and_average_wpm():
    s = summary([rec(words=30, duration_ms=60_000), rec(words=30, duration_ms=60_000)], 0, NOW)
    assert s.total_words == 60
    assert s.total_sessions == 2
    # Lifetime rate, not a mean of per-session rates.
    assert s.avg_wpm == 30


def test_best_wpm_ignores_blips():
    fast_blip = rec(words=2, duration_ms=200)      # too short and too few words
    real = rec(words=50, duration_ms=60_000)       # 50 wpm
    assert summary([fast_blip, real], 0, NOW).best_wpm == 50


def test_today_bucket_uses_local_time():
    s = summary([rec(words=7)], IST, NOW)
    assert s.words_today == 7


def test_last7_indexes_today_last():
    s = summary([rec(days_ago=0, words=1), rec(days_ago=6, words=5)], 0, NOW)
    assert s.last7_words[6] == 1
    assert s.last7_words[0] == 5
    # Anything older than a week is out of the window.
    assert summary([rec(days_ago=7, words=99)], 0, NOW).last7_words == [0] * 7


def test_streak_counts_consecutive_days():
    records = [rec(days_ago=d) for d in (0, 1, 2, 4)]
    assert summary(records, 0, NOW).day_streak == 3


def test_empty_today_does_not_break_the_streak():
    # Nothing dictated yet today, but yesterday and the day before count.
    records = [rec(days_ago=1), rec(days_ago=2)]
    assert summary(records, 0, NOW).day_streak == 2


def test_time_saved_is_never_negative():
    # Dictating slower than the typing baseline must read as zero, not a loss.
    slow = rec(words=1, duration_ms=600_000)
    assert summary([slow], 0, NOW).time_saved_secs == 0.0


def test_time_saved_uses_the_45wpm_baseline():
    # 45 words spoken in 6s: typing them would take 60s, so 54s saved.
    s = summary([rec(words=45, duration_ms=6_000)], 0, NOW)
    assert round(s.time_saved_secs) == 54


def test_wpm_edge_cases():
    assert wpm(0, 60) == 0
    assert wpm(10, 0) == 0


def test_local_day_shifts_with_the_offset():
    # 19:00 UTC is already the next day in IST (+05:30).
    ts = 1_770_000_000 // DAY_SECONDS * DAY_SECONDS + 19 * 3600
    assert local_day(ts, IST) == local_day(ts, 0) + 1
