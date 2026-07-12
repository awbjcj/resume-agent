from resume_agent.api.rate_limit import FailedAttemptLimiter


def test_failed_attempt_limiter_blocks_rolls_and_resets():
    limiter = FailedAttemptLimiter(max_failures=2, window_seconds=10)
    limiter.record_failure("alice", "127.0.0.1", now=100)
    limiter.record_failure("alice", "127.0.0.1", now=101)
    assert limiter.blocked("alice", "127.0.0.1", now=102)
    assert not limiter.blocked("alice", "127.0.0.1", now=112)
    limiter.record_failure("alice", "127.0.0.1", now=120)
    limiter.reset("alice", "127.0.0.1")
    assert not limiter.blocked("alice", "127.0.0.1", now=120)
