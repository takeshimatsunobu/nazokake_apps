from buggy import calculate_discount


def test_target_behavior():
    assert calculate_discount(100, 0.1) == 90
