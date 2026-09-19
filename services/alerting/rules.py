"""Pure rule functions: given current state, decide whether an alert type should be open.
Kept side-effect-free so they're trivial to unit test; main.py owns the polling/webhook loop
and the DB query that produces recent_stopper_count (alerting runs in its own process/container,
so state can't be held in-memory between ingestion and alerting - the DB is the shared state).
"""


def capacity_exceeded(current_count: int, capacity_max: int) -> bool:
    return current_count > capacity_max


def no_coverage(visitor_count: int, staff_count: int) -> bool:
    return visitor_count > 0 and staff_count == 0


def traffic_spike(recent_stopper_count: int, spike_threshold: int) -> bool:
    return recent_stopper_count >= spike_threshold
