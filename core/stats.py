"""Usage aggregation: words, speed, streaks, and time saved.

A pure function over a list of session records — storage stays in SQLite, and
the arithmetic here is testable without a database or a clock. The timezone
offset is a parameter for the same reason: day bucketing must not depend on
where the test runs or whether DST just flipped.

Ported from WhimprFlow's ``whimpr-core/src/stats.rs``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DAY_SECONDS = 86_400

#: Typing speed the time-saved estimate compares against. Matches the baseline
#: dictation tools cite (roughly 45 typed words per minute vs ~150 spoken).
TYPING_WPM_BASELINE = 45.0

#: A session must clear both bars before it can claim the "best WPM" title —
#: a two-word blip is arithmetic noise, not a personal record.
BEST_MIN_WORDS = 3
BEST_MIN_MS = 1000


@dataclass(frozen=True)
class SessionRecord:
    ts_unix: int
    words: int
    duration_ms: int


@dataclass
class StatsSummary:
    total_words: int = 0
    total_sessions: int = 0
    total_speaking_secs: float = 0.0
    avg_wpm: int = 0
    best_wpm: int = 0
    words_today: int = 0
    wpm_today: int = 0
    day_streak: int = 0
    #: Words per day for the last week; index 6 is today.
    last7_words: list[int] = field(default_factory=lambda: [0] * 7)
    time_saved_secs: float = 0.0


def wpm(words: int, seconds: float) -> int:
    """Words per minute, rounded. Zero when there is nothing to measure."""
    if seconds <= 0 or words <= 0:
        return 0
    return round(words / (seconds / 60.0))


def local_day(ts_unix: int, tz_offset_minutes: int) -> int:
    """Day index in the user's local timezone.

    ``tz_offset_minutes`` is minutes to *add* to local time to reach UTC, i.e.
    what JavaScript's ``getTimezoneOffset()`` returns (India: -330).
    """
    local = ts_unix - tz_offset_minutes * 60
    return local // DAY_SECONDS


def summary(records, tz_offset_minutes: int, now_unix: int) -> StatsSummary:
    """Aggregate session records into the numbers the dashboard shows."""
    records = list(records)
    out = StatsSummary()
    if not records:
        return out

    today = local_day(now_unix, tz_offset_minutes)
    active_days = set()
    words_today = 0
    secs_today = 0.0

    for rec in records:
        out.total_words += rec.words
        out.total_sessions += 1
        seconds = rec.duration_ms / 1000.0
        out.total_speaking_secs += seconds

        day = local_day(rec.ts_unix, tz_offset_minutes)
        active_days.add(day)

        if day == today:
            words_today += rec.words
            secs_today += seconds

        ago = today - day
        if 0 <= ago < 7:
            out.last7_words[6 - ago] += rec.words

        if rec.words >= BEST_MIN_WORDS and rec.duration_ms >= BEST_MIN_MS:
            out.best_wpm = max(out.best_wpm, wpm(rec.words, seconds))

    out.avg_wpm = wpm(out.total_words, out.total_speaking_secs)
    out.words_today = words_today
    out.wpm_today = wpm(words_today, secs_today)
    out.day_streak = _streak(active_days, today)
    # Never negative: dictating slower than you type is not "time lost", it is
    # just a bad measurement to show someone.
    out.time_saved_secs = max(
        0.0, out.total_words / TYPING_WPM_BASELINE * 60.0 - out.total_speaking_secs
    )
    return out


def _streak(active_days: set[int], today: int) -> int:
    """Consecutive active days ending today.

    A day with no dictations yet does not break the streak until it is fully
    past — counting from yesterday when today is still empty.
    """
    day = today if today in active_days else today - 1
    streak = 0
    while day in active_days:
        streak += 1
        day -= 1
    return streak
