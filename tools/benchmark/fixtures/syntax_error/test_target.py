from buggy import shout


def test_target_behavior():
    assert shout("hello") == "HELLO!"
