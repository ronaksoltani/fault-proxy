import pytest

from fault_proxy.app import Settings, choose_fault


def test_fault_selection_is_repeatable_for_a_known_random_value():
    assert choose_fault(0.05, 0.10, 0.20) == "error"
    assert choose_fault(0.15, 0.10, 0.20) == "delay"
    assert choose_fault(0.80, 0.10, 0.20) == "pass"


def test_settings_reject_invalid_upstream_and_rates():
    with pytest.raises(ValueError):
        Settings("file:///tmp/secret")
    with pytest.raises(ValueError):
        Settings("http://localhost:9000", error_rate=1.5)
