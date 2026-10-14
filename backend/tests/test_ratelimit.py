from datetime import date

from app.ratelimit import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_per_client_window_blocks_then_recovers():
    clock = FakeClock()
    rl = RateLimiter(clock=clock)
    assert [rl.check_client("a", 3) for _ in range(3)] == [None, None, None]
    retry = rl.check_client("a", 3)
    assert retry == 60  # oldest request leaves the window in 60 s
    clock.now += 61
    assert rl.check_client("a", 3) is None


def test_clients_are_limited_independently():
    rl = RateLimiter(clock=FakeClock())
    assert rl.check_client("a", 1) is None
    assert rl.check_client("a", 1) is not None
    assert rl.check_client("b", 1) is None


def test_zero_means_unlimited():
    rl = RateLimiter(clock=FakeClock())
    assert all(rl.check_client("a", 0) is None for _ in range(100))
    assert all(rl.check_daily(0) for _ in range(100))


def test_daily_cap_resets_on_a_new_day():
    day = {"today": date(2026, 10, 14)}
    rl = RateLimiter(today=lambda: day["today"])
    assert [rl.check_daily(2) for _ in range(3)] == [True, True, False]
    day["today"] = date(2026, 10, 15)
    assert rl.check_daily(2) is True
