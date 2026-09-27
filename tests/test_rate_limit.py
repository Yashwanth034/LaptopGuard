from laptopguard.rate_limit import RateLimiter


def test_rate_limiter_blocks_until_window_expires():
    now = [100.0]
    limiter = RateLimiter(60, clock=lambda: now[0])
    assert limiter.allow('failed_auth') is True
    assert limiter.allow('failed_auth') is False
    now[0] = 161.0
    assert limiter.allow('failed_auth') is True
