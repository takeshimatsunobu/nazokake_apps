"""
tools/extract_dataset.py
==========================
ローカルSQLite(NazokakeItemORM)から、human_evaluations(人間評価)が1件以上ある、
または is_golden_data=True(殿堂入り)のレコードを抽出し、機械学習モデルの過学習・
データ汚染を防ぐための厳格な閾値判定・デデュプリケーション・匿名化を経て、
SFT用(data/sft_dataset.jsonl)およびDPO用(data/dpo_dataset.jsonl)のJSONLデータセットを
出力する。

抽出→コアーセット・リプレイのプール選定(未学習の最新データ85% + 過去の学習済み
高評価/goldenデータから層化抽出した15%のコアーセット)→閾値判定(chosen/rejected、
中間スコアはドロップ)→デデュプリケーション→匿名化→JSONL書き出し→trained_atの
更新、の順に処理する。

【コアーセット・リプレイ(破滅的忘却対策)】 毎回「未学習の最新データ」のみで学習すると、
過去に学習した知識(パターン)を新しい学習で上書きしてしまう(破滅的忘却)。そのため、
NazokakeItemORM.trained_at(NULL=未学習)で「未学習の最新データ」プールと「過去の
学習済みデータ」プールを区別し、後者からスコア分布・お題(トピック)の多様性を
担保する層化抽出法で少量(CORESET_RATIO)のコアーセットを毎回リプレイ用に混ぜ込む。

使い方:
    uv run python tools/extract_dataset.py
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from datasketch import MinHash, MinHashLSH
from sqlalchemy import or_, select

from nazokake_core.database import (
    NazokakeItemORM,
    async_mark_trained,
    ensure_db_ready,
    get_session,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data"
SFT_OUTPUT_PATH = OUTPUT_DIR / "sft_dataset.jsonl"
DPO_OUTPUT_PATH = OUTPUT_DIR / "dpo_dataset.jsonl"
EXTRACTION_STATS_PATH = OUTPUT_DIR / "extraction_stats.json"

# DPO(Direct Preference Optimization)の厳格な閾値: スコア4以上をchosen、2以下を
# rejectedとし、中間スコア(2<score<4)はノイズとして容赦なく除外(Drop)する。
CHOSEN_SCORE_MIN = 4.0
REJECTED_SCORE_MAX = 2.0

# 同一お題(odai)あたりのDPOペア生成数の上限(組み合わせ爆発とノイズの多重抽出を防ぐ)。
MAX_PAIRS_PER_ODAI = 5

# --- コアーセット・リプレイ(破滅的忘却対策) --------------------------------
# 「未学習の最新データ」プールから抽出する割合(残りは今回は見送り、次回以降に回す)。
NEW_DATA_SAMPLE_RATIO = float(os.environ.get("NEW_DATA_SAMPLE_RATIO", "0.85"))
# 「過去の学習済みデータ(is_golden_data=True または高評価)」プールから層化抽出で
# リプレイ用コアーセットとして抽出する割合。環境変数 CORESET_RATIO で上書き可能。
CORESET_RATIO = float(os.environ.get("CORESET_RATIO", "0.15"))
# スコア帯の層化バケツ幅(この幅で四捨五入したスコアを層化キーの一部とする)。
SCORE_BUCKET_WIDTH = 0.5

# 文字ベースn-gramのサイズ(MinHashに渡す特徴集合の粒度)。
NGRAM_SIZE = 3
# MinHashの精度(permutation数)。大きいほどJaccard類似度の推定精度が上がるが計算コストも増える。
MINHASH_NUM_PERM = 128
# MinHashLSHの類似度閾値(Jaccard近似)。この値以上なら「実質的に同一パターンの重複」とみなす。
LSH_SIMILARITY_THRESHOLD = 0.87

# n-gram生成前に除去する対象(空白・記号)。\wはUnicode文字(漢字・かな含む)にマッチするため、
# 意味のある文字だけを残して軽量な特徴集合を作れる。
_NON_TOKEN_CHARS = re.compile(r"[\s\W]+")


@dataclass
class Candidate:
    doc_id: str
    odai: str
    answer_text: str
    score: float | None
    is_golden: bool
    trained_at: str | None


def _primary_answer_text(row: dict) -> str | None:
    """Gemini(主軸)の回答を優先し、無ければELYZA/LocalLLMの回答を使う。"""
    text = row.get("nazokake_text") or row.get("nazokake_text_llmjp")
    return text.strip() if text else None


def _record_score(row: dict) -> float | None:
    """human_evaluationsのuser_score群の平均を、そのレコードの代表スコアとする。

    最大値ではなく平均値を採用する: 単一の甘い(または厳しい)評価者1件だけで
    閾値判定が引っ張られてしまうことを避けるため。
    """
    evaluations = row.get("human_evaluations") or []
    scores = [
        e["user_score"]
        for e in evaluations
        if isinstance(e.get("user_score"), (int, float))
    ]
    return mean(scores) if scores else None


async def _fetch_candidates() -> list[Candidate]:
    """human_evaluations が1件以上あるか is_golden_data=True のレコードを抽出する。"""
    async with get_session() as session:
        result = await session.execute(
            select(NazokakeItemORM).where(
                or_(
                    NazokakeItemORM.human_evaluations.isnot(None),
                    NazokakeItemORM.is_golden_data.is_(True),
                )
            )
        )
        rows = result.scalars().all()
        row_dicts = [
            {c.name: getattr(row, c.name) for c in NazokakeItemORM.__table__.columns}
            for row in rows
        ]

    candidates: list[Candidate] = []
    for row in row_dicts:
        # SQLの上記WHEREはhuman_evaluationsがNULLでないもの(空リスト[]も含む)を
        # 拾うため、「1件以上ある」という意味の「存在する」はここでPython側で厳密化する。
        has_human_eval = bool(row.get("human_evaluations"))
        if not has_human_eval and not row.get("is_golden_data"):
            continue

        answer_text = _primary_answer_text(row)
        odai = (row.get("odai") or "").strip()
        if not answer_text or not odai:
            continue

        candidates.append(
            Candidate(
                doc_id=row["doc_id"],
                odai=odai,
                answer_text=answer_text,
                score=_record_score(row),
                is_golden=bool(row.get("is_golden_data")),
                trained_at=row.get("trained_at"),
            )
        )
    return candidates


def _stratify_key(candidate: Candidate) -> tuple[str, str]:
    """お題(トピック)とスコア帯の組み合わせを層化抽出のキーとする。

    is_golden_dataでスコアが無いレコードは専用バケツ("golden_or_unscored")に
    まとめる(スコアが無いことをもって除外せず、golden自体を1つの層として扱う)。
    """
    if candidate.score is None:
        score_bucket = "golden_or_unscored"
    else:
        bucket_index = round(candidate.score / SCORE_BUCKET_WIDTH)
        score_bucket = f"{bucket_index * SCORE_BUCKET_WIDTH:.1f}"
    return (candidate.odai, score_bucket)


def stratified_sample(
    candidates: list[Candidate], ratio: float, rng: random.Random
) -> list[Candidate]:
    """お題(トピック)×スコア帯で層化し、各層から比例的にサンプリングする。

    スコア分布・お題の多様性が担保されたコアーセット(リプレイ用)を抽出することが
    目的。層のサイズが大きい順に目標件数を割り当てることで、四捨五入による
    丸め誤差を大きい層側に寄せ、小さい層が丸めで0件に切り捨てられて合計が
    不足しがちな問題を緩和する。
    """
    if not candidates or ratio <= 0:
        return []
    target_total = min(len(candidates), round(len(candidates) * ratio))
    if target_total <= 0:
        return []

    strata: dict[tuple[str, str], list[Candidate]] = {}
    for c in candidates:
        strata.setdefault(_stratify_key(c), []).append(c)

    sampled: list[Candidate] = []
    remaining_target = target_total
    for key in sorted(strata, key=lambda k: len(strata[k]), reverse=True):
        if remaining_target <= 0:
            break
        group = strata[key]
        stratum_target = max(1, round(target_total * len(group) / len(candidates)))
        stratum_target = min(stratum_target, len(group), remaining_target)
        sampled.extend(rng.sample(group, stratum_target))
        remaining_target -= stratum_target

    return sampled


def select_training_pool(
    candidates: list[Candidate], rng: random.Random | None = None
) -> tuple[list[Candidate], dict]:
    """コアーセット・リプレイのプール選定: 「未学習の最新データ」85% +
    「過去の学習済み(golden/高評価)データ」から層化抽出した15%のコアーセット。

    戻り値は (今回の学習に使う候補リスト, 統計情報dict)。統計情報は
    tools/mlops_pipeline_nazo.pyが実験ログ(mlops_experiments.db)へ記録する際、
    およびdata/extraction_stats.jsonへの記録に使う。
    """
    rng = rng or random.Random()

    new_pool = [c for c in candidates if c.trained_at is None]
    old_pool = [c for c in candidates if c.trained_at is not None]
    replay_source_pool = [
        c for c in old_pool if c.is_golden or (c.score is not None and c.score >= CHOSEN_SCORE_MIN)
    ]

    new_sample = rng.sample(
        new_pool, min(len(new_pool), round(len(new_pool) * NEW_DATA_SAMPLE_RATIO))
    )
    coreset_sample = stratified_sample(replay_source_pool, CORESET_RATIO, rng)

    selected = new_sample + coreset_sample
    stats = {
        "candidates_total": len(candidates),
        "new_pool_size": len(new_pool),
        "new_sample_size": len(new_sample),
        "replay_source_pool_size": len(replay_source_pool),
        "coreset_sample_size": len(coreset_sample),
        "dataset_size": len(selected),
        "new_data_sample_ratio": NEW_DATA_SAMPLE_RATIO,
        "coreset_ratio": CORESET_RATIO,
        "new_sample_doc_ids": [c.doc_id for c in new_sample],
    }
    return selected, stats


def classify(candidates: list[Candidate]) -> tuple[list[Candidate], list[Candidate]]:
    """厳格な閾値判定: is_golden_dataまたはスコア4以上をchosen、スコア2以下をrejectedとする。

    中間スコア(2<score<4)かつ非goldenのレコード、およびスコアも無くgoldenでもない
    レコードは、ノイズとして容赦なく除外(Drop)する。
    """
    chosen: list[Candidate] = []
    rejected: list[Candidate] = []
    for c in candidates:
        if c.is_golden:
            chosen.append(c)
            continue
        if c.score is None:
            continue
        if c.score >= CHOSEN_SCORE_MIN:
            chosen.append(c)
        elif c.score <= REJECTED_SCORE_MAX:
            rejected.append(c)
        # else: 中間スコアはドロップ
    return chosen, rejected


def _validate_pair(prompt: str, chosen_text: str, rejected_text: str) -> bool:
    """prompt/chosen/rejectedの論理的対応を検証する。

    3者とも空でなく、chosenとrejectedが同一テキストでないこと(同一なら選好の
    比較として無意味)を確認する。
    """
    if not prompt or not chosen_text or not rejected_text:
        return False
    return chosen_text.strip() != rejected_text.strip()


def build_sft_records(chosen: list[Candidate]) -> list[dict]:
    """chosen(is_golden_dataまたは高評価)のレコードだけをSFTの模範例として採用する。"""
    return [{"prompt": c.odai, "completion": c.answer_text} for c in chosen]


def build_dpo_pairs(chosen: list[Candidate], rejected: list[Candidate]) -> list[dict]:
    """同一お題(odai)内でchosen×rejectedの組み合わせを作り、DPOペアとする。"""
    chosen_by_odai: dict[str, list[Candidate]] = {}
    for c in chosen:
        chosen_by_odai.setdefault(c.odai, []).append(c)
    rejected_by_odai: dict[str, list[Candidate]] = {}
    for r in rejected:
        rejected_by_odai.setdefault(r.odai, []).append(r)

    pairs: list[dict] = []
    for odai, chosen_group in chosen_by_odai.items():
        rejected_group = rejected_by_odai.get(odai)
        if not rejected_group:
            continue
        combos = itertools.islice(
            itertools.product(chosen_group, rejected_group), MAX_PAIRS_PER_ODAI
        )
        for c, r in combos:
            if not _validate_pair(odai, c.answer_text, r.answer_text):
                continue
            pairs.append(
                {"prompt": odai, "chosen": c.answer_text, "rejected": r.answer_text}
            )
    return pairs


def _ngram_tokens(text: str, n: int = NGRAM_SIZE) -> set[str]:
    """テキストから空白・記号を除去し、文字ベースのn-gram集合を生成する軽量トークナイザー。

    difflib.SequenceMatcherによる逐次比較(O(N^2))を避け、MinHash/LSHへ渡すための
    軽量な特徴集合(Set)を作ることが目的。
    """
    cleaned = _NON_TOKEN_CHARS.sub("", text.lower())
    if not cleaned:
        return set()
    if len(cleaned) < n:
        return {cleaned}
    return {cleaned[i : i + n] for i in range(len(cleaned) - n + 1)}


def _build_minhash(tokens: set[str]) -> MinHash:
    """n-gramトークン集合からMinHashシグネチャを計算する。"""
    m = MinHash(num_perm=MINHASH_NUM_PERM)
    for token in tokens:
        m.update(token.encode("utf-8"))
    return m


def _dedupe_by_minhash_lsh(records: list[dict], text_key: str) -> list[dict]:
    """同一prompt内で、text_key(SFTならcompletion、DPOならchosen)の内容がMinHash/LSHにより
    類似(衝突)すると判定されたレコードを除外する。

    プロンプトごとに独立したMinHashLSHインデックスを持つ(異なるお題の回答同士を誤って
    重複判定しないため)。抽出済みレコードを1件ずつLSHへクエリし、類似するものが既に
    無ければインデックスへ追加して出力対象とする(datasketchのバンディング法により
    クエリ・挿入とも近似O(1)であり、difflib.SequenceMatcherの総当たり比較のような
    O(N^2)の計算爆発を起こさない)。
    """
    lsh_by_prompt: dict[str, MinHashLSH] = {}
    kept: list[dict] = []

    for idx, rec in enumerate(records):
        prompt = rec["prompt"]
        lsh = lsh_by_prompt.setdefault(
            prompt,
            MinHashLSH(threshold=LSH_SIMILARITY_THRESHOLD, num_perm=MINHASH_NUM_PERM),
        )

        minhash = _build_minhash(_ngram_tokens(rec[text_key]))
        if lsh.query(minhash):
            continue  # 類似(衝突)する既存レコードが見つかったため重複として除外

        lsh.insert(f"{prompt}::{idx}", minhash)
        kept.append(rec)

    return kept


def dedupe_sft(records: list[dict]) -> list[dict]:
    """同一prompt内でcompletionがMinHash/LSHにより類似判定される重複を除外する。"""
    return _dedupe_by_minhash_lsh(records, "completion")


def dedupe_dpo(records: list[dict]) -> list[dict]:
    """同一prompt内でchosenがMinHash/LSHにより類似判定される重複を除外する。"""
    return _dedupe_by_minhash_lsh(records, "chosen")


# tools/nazo_agent.py の sanitize_pii() と同系統(メール/クレデンシャル/Bearerトークン/
# 電話番号らしき数字パターン)に、Windowsローカルパス(C:\Users\...)検知を追加した
# 独立実装。nazo_agent.py はAnthropic/httpx等への依存とモジュールレベルのNO_PROXY副作用を
# 持つため、データセット抽出という無関係な処理からそのモジュールへ結合させないよう
# 意図的に複製する。
_SANITIZE_PATTERNS = [
    # Windowsのローカル絶対パス(例: C:\Users\name\project\file.py)
    (re.compile(r"[A-Za-z]:\\(?:[^\\\r\n]+\\)*[^\\\r\n]+"), "[PATH MASKED]"),
    # メールアドレス
    (re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"), "[EMAIL MASKED]"),
    # クレデンシャル/APIキーの典型パターン(sk-... 形式)
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "[CREDENTIAL MASKED]"),
    # Bearerトークン
    (re.compile(r"Bearer\s+[a-zA-Z0-9\-._~+/]+=*"), "[CREDENTIAL MASKED]"),
    # 電話番号らしき連続した数字パターン(2〜4桁-2〜4桁-4桁)
    (re.compile(r"\d{2,4}-\d{2,4}-\d{4}"), "[NUMBER MASKED]"),
]


def sanitize_text(text: str) -> str:
    """テキスト中のローカルパス・メールアドレス・APIキー・電話番号等をマスキングする。"""
    for pattern, replacement in _SANITIZE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            # json.dumpsは文字列中の改行・引用符・カンマ等をJSON仕様通りにエスケープする
            # ため、1レコード1行のJSONL出力として構造が破壊されることはない。
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> int:
    # DBファイルが存在しない、またはテーブル未作成(スキーマ未初期化)の環境でも
    # 即座に例外で落ちないよう、クエリ前に必ずテーブルの存在を保証する
    # (CREATE TABLE IF NOT EXISTS相当、既存データは変更しない)。
    ensure_db_ready()

    candidates = asyncio.run(_fetch_candidates())
    print(f"抽出候補: {len(candidates)}件")

    selected, pool_stats = select_training_pool(candidates)
    print(
        f"コアーセット・リプレイ: 未学習の最新データ {pool_stats['new_sample_size']}件"
        f"(プール{pool_stats['new_pool_size']}件中) + "
        f"層化抽出コアーセット {pool_stats['coreset_sample_size']}件"
        f"(リプレイ候補プール{pool_stats['replay_source_pool_size']}件中) "
        f"= 合計{pool_stats['dataset_size']}件"
    )

    chosen, rejected = classify(selected)
    print(
        f"chosen: {len(chosen)}件 / rejected: {len(rejected)}件 (中間スコアはドロップ済み)"
    )

    sft_records = dedupe_sft(build_sft_records(chosen))
    sft_records = [
        {
            "prompt": sanitize_text(r["prompt"]),
            "completion": sanitize_text(r["completion"]),
        }
        for r in sft_records
    ]

    dpo_pairs = dedupe_dpo(build_dpo_pairs(chosen, rejected))
    dpo_pairs = [
        {
            "prompt": sanitize_text(p["prompt"]),
            "chosen": sanitize_text(p["chosen"]),
            "rejected": sanitize_text(p["rejected"]),
        }
        for p in dpo_pairs
    ]

    _write_jsonl(sft_records, SFT_OUTPUT_PATH)
    _write_jsonl(dpo_pairs, DPO_OUTPUT_PATH)

    print(
        f"✅ SFTデータセットを書き出しました: {SFT_OUTPUT_PATH} ({len(sft_records)}件)"
    )
    print(f"✅ DPOデータセットを書き出しました: {DPO_OUTPUT_PATH} ({len(dpo_pairs)}件)")

    # 「未学習の最新データ」プールから今回サンプリングされたレコードのみtrained_atを
    # 更新する(リプレイ用コアーセットは既に学習済みのため、元のtrained_atを保持する)。
    new_sample_doc_ids = pool_stats["new_sample_doc_ids"]
    asyncio.run(async_mark_trained(new_sample_doc_ids))
    print(f"✅ trained_atを更新しました: {len(new_sample_doc_ids)}件")

    stats_record = {
        "sft_record_count": len(sft_records),
        "dpo_pair_count": len(dpo_pairs),
        **{k: v for k, v in pool_stats.items() if k != "new_sample_doc_ids"},
    }
    EXTRACTION_STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXTRACTION_STATS_PATH.write_text(
        json.dumps(stats_record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✅ 抽出統計を書き出しました: {EXTRACTION_STATS_PATH}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
