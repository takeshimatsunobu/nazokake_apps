from stable import greet


def test_sanity_behavior():
    assert greet("World") == "Hello, World!"
