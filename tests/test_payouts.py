from app.services.payouts import compute_payouts
import pytest

def test_entryfee_zero():
    participants = [{'user_id': 'user1', 'outcome': 'verified'}]
    try:
        compute_payouts(participants, 0)
    except ValueError as e:
        assert str(e) == "Entry fee must be greater than zero."
    else:
        assert False, "Expected ValueError for entry fee of zero"
def test_entryfee_negative():
    participants = [{'user_id': 'user1', 'outcome': 'verified'}]
    try:
        compute_payouts(participants, -10)
    except ValueError as e:
        assert str(e) == "Entry fee must be greater than zero."
    else:
        assert False, "Expected ValueError for negative entry fee"
def test_no_participants():
    participants = []
    result = compute_payouts(participants, 100)
    assert result == {}, "Expected empty dictionary for no participants"
def test_all_forfeiters():
    participants = [{'user_id': 'user1', 'outcome': 'forfeited'}, {'user_id': 'user2', 'outcome': 'forfeited'}]
    result = compute_payouts(participants, 100)
    expected = {'user1': 100, 'user2': 100}
    assert result == expected, f"Expected {expected}, got {result}"
def test_all_completers():
    participants = [{'user_id': 'user1', 'outcome': 'verified'}, {'user_id': 'user2', 'outcome': 'verified'}]
    result = compute_payouts(participants, 100)
    expected = {'user1': 100, 'user2': 100}
    assert result == expected, f"Expected {expected}, got {result}"
def test_mixed_1_winner():
    participants = [{'user_id': 'user1', 'outcome': 'verified'}, {'user_id': 'user2', 'outcome': 'forfeited'}, {'user_id': 'user3', 'outcome': 'pending'}]
    result = compute_payouts(participants, 100)
    expected = {'user1': 300, 'user2': 0,'user3': 0}
    assert result == expected, f"Expected {expected}, got {result}"
def test_mixed_2_winners():
    participants = [{'user_id': 'user1', 'outcome': 'verified'}, {'user_id': 'user2', 'outcome': 'verified'}, {'user_id': 'user3', 'outcome': 'forfeited'}]
    result = compute_payouts(participants, 20)
    expected = {'user1': 30, 'user2': 30, 'user3': 0}
    assert result == expected, f"Expected {expected}, got {result}"
