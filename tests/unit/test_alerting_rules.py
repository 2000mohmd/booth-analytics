from services.alerting.rules import capacity_exceeded, no_coverage, traffic_spike


def test_capacity_exceeded():
    assert capacity_exceeded(16, capacity_max=15) is True
    assert capacity_exceeded(15, capacity_max=15) is False


def test_no_coverage_only_when_visitors_present():
    assert no_coverage(visitor_count=3, staff_count=0) is True
    assert no_coverage(visitor_count=0, staff_count=0) is False
    assert no_coverage(visitor_count=3, staff_count=1) is False


def test_traffic_spike_threshold():
    assert traffic_spike(recent_stopper_count=10, spike_threshold=10) is True
    assert traffic_spike(recent_stopper_count=9, spike_threshold=10) is False
