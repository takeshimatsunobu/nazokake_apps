def rank_scores(scores, threshold):
    """thresholdを超えるスコアを、元のインデックスとスコアのペアとして
    降順(高い方が先)に並べ替えて返す。"""
    ranked = []
    for i in range(len(scores)):
        if scores[i] > threshold:
            ranked.append((i, scores[i] * 2))
    return sorted(ranked, key=lambda pair: pair[1])
