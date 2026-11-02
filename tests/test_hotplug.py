from soundrec.hotplug import DeviceWatcher, compare, settle_loop


def test_compare():
    change = compare({"a": 1, "b": 1, "c": 4}, {"b": 1, "c": 1, "d": 1})
    assert change.appeared == ("d",)
    assert change.vanished == ("a",)
    assert change.changed == ("c",)
    assert change
    assert not compare({"a": 1}, {"a": 1})


def run(events, settle=1.0):
    """settle_loop over a script of wait() results; returns (timeouts asked, calls)."""
    events = iter(events)
    timeouts, calls = [], []

    def wait(timeout):
        timeouts.append(timeout)
        return next(events)

    settle_loop(wait, settle, lambda: calls.append(len(timeouts)))
    return timeouts, calls


def test_a_burst_is_reported_once_after_it_settles():
    timeouts, calls = run(["change", "change", "change", "timeout", "stop"])
    assert calls == [4]
    assert timeouts == [None, 1.0, 1.0, 1.0, None]


def test_two_bursts_two_calls():
    _, calls = run(["change", "timeout", "change", "change", "timeout", "stop"])
    assert calls == [2, 5]


def test_stop_mid_burst_reports_nothing():
    _, calls = run(["change", "stop"])
    assert calls == []


def test_watcher_starts_and_stops_on_this_machine():
    watcher = DeviceWatcher(lambda change: None, settle=0.1)
    watcher.start()
    watcher.stop()
    assert watcher.error is None
