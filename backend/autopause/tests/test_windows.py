"""SlidingWindow: event-time counting, eviction, and key isolation."""

from datetime import timedelta

from backend.autopause.mocks import _BASE_TIME
from backend.autopause.windows import SlidingWindow


def test_counts_within_window():
    w = SlidingWindow(window_seconds=60)
    assert w.add("k", _BASE_TIME) == 1
    assert w.add("k", _BASE_TIME + timedelta(seconds=10)) == 2
    assert w.add("k", _BASE_TIME + timedelta(seconds=20)) == 3


def test_evicts_stale_events():
    w = SlidingWindow(window_seconds=60)
    w.add("k", _BASE_TIME)
    w.add("k", _BASE_TIME + timedelta(seconds=30))
    # This event is >60s after the first; the first falls out of the window.
    count = w.add("k", _BASE_TIME + timedelta(seconds=90))
    assert count == 2


def test_boundary_event_exactly_at_edge_is_kept():
    # cutoff is `at - window`; eviction is strict `< cutoff`, so an event exactly
    # `window` seconds before `at` is still counted.
    w = SlidingWindow(window_seconds=60)
    w.add("k", _BASE_TIME)
    count = w.add("k", _BASE_TIME + timedelta(seconds=60))
    assert count == 2


def test_keys_are_isolated():
    w = SlidingWindow(window_seconds=60)
    w.add(("tenant-a", "camp-1"), _BASE_TIME)
    w.add(("tenant-a", "camp-1"), _BASE_TIME)
    assert w.add(("tenant-b", "camp-1"), _BASE_TIME) == 1
    assert w.count(("tenant-a", "camp-1")) == 2


def test_reset_clears_key():
    w = SlidingWindow(window_seconds=60)
    w.add("k", _BASE_TIME)
    w.reset("k")
    assert w.count("k") == 0
