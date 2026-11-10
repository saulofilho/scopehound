from scopehound.guardrails import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def test_rate_is_enforced():
    clock = FakeClock()
    limiter = RateLimiter(2.0, clock=clock, sleep=clock.sleep)
    for _ in range(5):
        await limiter.acquire()
    assert clock.slept == [0.5] * 4
    assert clock.now == 2.0


async def test_idle_time_refills_up_to_burst():
    clock = FakeClock()
    limiter = RateLimiter(1.0, burst=2, clock=clock, sleep=clock.sleep)
    clock.now = 100.0
    await limiter.acquire()
    await limiter.acquire()
    assert clock.slept == []
    await limiter.acquire()
    assert clock.slept == [1.0]
