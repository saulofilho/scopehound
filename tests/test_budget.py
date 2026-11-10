import pytest

from scopehound.guardrails import Budget, BudgetExhausted, KillSwitch, KillSwitchTripped


def test_limits_are_inclusive_and_failed_consume_not_counted():
    b = Budget(max_steps=2, max_requests=2, max_tokens=100)
    b.consume_step()
    b.consume_step()
    with pytest.raises(BudgetExhausted):
        b.consume_step()
    assert b.steps == 2
    b.consume_tokens(100)
    with pytest.raises(BudgetExhausted):
        b.consume_tokens(1)


def test_child_charges_parent():
    parent = Budget(max_steps=10, max_requests=5, max_tokens=1000)
    a = parent.child(max_requests=3)
    b = parent.child(max_requests=3)
    a.consume_request(3)
    b.consume_request(2)
    assert parent.requests == 5
    with pytest.raises(BudgetExhausted):
        b.consume_request(1)  # cabe no filho, não no pai
    assert b.requests == 2


def test_child_defaults_to_remaining():
    parent = Budget(max_steps=10, max_requests=5, max_tokens=1000)
    parent.consume_request(4)
    assert parent.child().max_requests == 1


def test_negative_rejected():
    with pytest.raises(ValueError):
        Budget(1, 1, 1).consume_tokens(-5)


def test_kill_switch():
    ks = KillSwitch()
    ks.check()
    ks.trip("operador")
    ks.trip("outro")
    assert ks.reason == "operador"
    with pytest.raises(KillSwitchTripped):
        ks.check()
