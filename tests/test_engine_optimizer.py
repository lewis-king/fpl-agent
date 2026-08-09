import pytest

from fplagent_engine.optimizer import _next_free_transfer_bank, _solve, _weights


def test_future_weights_decay_without_discarding_later_gameweeks() -> None:
    weights = _weights([1, 2, 3], decay=0.88)

    assert weights == {1: 1.0, 2: 0.88, 3: 0.88**2}


def test_free_transfers_roll_to_live_cap() -> None:
    available = 1
    for _ in range(8):
        available = _next_free_transfer_bank(available, used=0, maximum=5)

    assert available == 5
    assert _next_free_transfer_bank(available, used=5, maximum=5) == 1


def test_free_transfer_overspend_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid free-transfer state"):
        _next_free_transfer_bank(available=2, used=3, maximum=5)


def test_invalid_bench_proxy_weight_is_rejected_before_solving() -> None:
    with pytest.raises(ValueError, match="bench_autosub_weight"):
        _solve([], [], bench_autosub_weight=1.01)


def test_invalid_gw1_defender_count_is_rejected_before_solving() -> None:
    with pytest.raises(ValueError, match="gw1_defenders"):
        _solve([], [], gw1_defenders=2)


def test_invalid_forbidden_transfer_event_is_rejected_before_solving() -> None:
    with pytest.raises(ValueError, match="forbid_transfer_events"):
        _solve([], [1, 2, 3], forbid_transfer_events={1})
