from buggy import rank_scores


def test_target_behavior():
    assert rank_scores([10, 50, 30, 80], 20) == [(3, 80), (1, 50), (2, 30)]
