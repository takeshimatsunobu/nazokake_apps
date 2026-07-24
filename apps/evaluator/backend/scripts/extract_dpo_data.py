"""DPO（Direct Preference Optimization）選好ペア抽出スクリプト（MLOps 特化 V3）。

10,000人規模の学習効率を最大化する「All-Pairs Comparison（全組み合わせ網羅）」、
過学習を防ぐ「MAX_PAIRS_PER_GROUP (上位5件抽出)」、および
Hugging Face trl 互換を保証する「_metadataパージ」を実装した完全防弾エンジン。

入力 (data/rlhf_dataset.jsonl, 1行1サンプル):
  { "odai", "model", "text", "score", "score_type", "doc_id", "dpo_pair_id", ... }

出力 (data/dpo_dataset.jsonl, 1行1ペア):
  { "prompt": "お題「{odai}」でなぞかけを作成してください。",
    "chosen": "<高スコア>", "rejected": "<低スコア>" }
"""

import argparse
import json
import os
import sys
from collections import defaultdict
import itertools

# 過学習を防ぐための、1つの(お題×評価軸)から生成するペアの最大数
MAX_PAIRS_PER_GROUP = 5

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: S110 (reconfigure非対応環境向けの意図的なフォールバック)
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
DEFAULT_IN = os.path.join(PROJECT_ROOT, "data", "rlhf_dataset.jsonl")
DEFAULT_OUT = os.path.join(PROJECT_ROOT, "data", "dpo_dataset.jsonl")


def load_records(in_path: str):
    records = []
    with open(in_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception as e:
                print(f"⚠️ {i}行目をスキップ（JSON不正）: {e}")
    return records


def to_score(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_pairs(records):
    groups = defaultdict(lambda: defaultdict(list))

    for r in records:
        group_key = r.get("dpo_pair_id") or r.get("doc_id")
        text = (r.get("text") or "").strip()
        score = to_score(r.get("score"))
        score_type = r.get("score_type", "unknown")

        if not group_key or not text or score is None:
            continue

        groups[group_key][score_type].append(
            {
                "text": text,
                "score": score,
                "odai": r.get("odai", ""),
                "model": r.get("model", ""),
            }
        )

    pairs = []
    stats = {
        "groups": len(groups),
        "single": 0,
        "tie": 0,
        "same_text": 0,
        "cross_type": 0,
        "paired": 0,
    }

    for group_key, type_dict in groups.items():
        if len(list(type_dict.keys())) > 1:
            stats["cross_type"] += 1

        for stype, items in type_dict.items():
            if len(items) < 2:
                stats["single"] += 1
                continue

            local_pairs = []
            for item1, item2 in itertools.combinations(items, 2):
                if item1["score"] == item2["score"]:
                    stats["tie"] += 1
                    continue
                if item1["text"] == item2["text"]:
                    stats["same_text"] += 1
                    continue

                chosen, rejected = (
                    (item1, item2)
                    if item1["score"] > item2["score"]
                    else (item2, item1)
                )
                odai = chosen.get("odai") or rejected.get("odai") or ""

                local_pairs.append(
                    {
                        "prompt": f"お題「{odai}」でなぞかけを作成してください。",
                        "chosen": chosen["text"],
                        "rejected": rejected["text"],
                        "_metadata": {
                            "group_key": group_key,
                            "score_type": stype,
                            "score_diff": round(chosen["score"] - rejected["score"], 2),
                        },
                    }
                )

            # 過学習防止: スコア差が大きい上位ペアのみを学習データに採用（足切り）
            local_pairs.sort(key=lambda x: x["_metadata"]["score_diff"], reverse=True)
            local_pairs = local_pairs[:MAX_PAIRS_PER_GROUP]

            pairs.extend(local_pairs)
            stats["paired"] += len(local_pairs)

    return pairs, stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="in_path", default=DEFAULT_IN)
    parser.add_argument("--out", dest="out_path", default=DEFAULT_OUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not os.path.exists(args.in_path):
        print(f"❌ 入力が見つかりません: {args.in_path}")
        return

    records = load_records(args.in_path)
    pairs, stats = build_pairs(records)

    print(f"📥 入力レコード={len(records)} / 抽出グループ={stats['groups']}")
    print(
        f"⏭️  スキップ: 孤立(Solo)={stats['single']} / 同点(Tie)={stats['tie']} / 本文同一={stats['same_text']}"
    )
    print(
        f"🛡️  データ汚染回避: 異種スコア混在グループ={stats['cross_type']} (分離して比較)"
    )
    print(
        f"✅ DPO選好ペア総数: {stats['paired']} 件 (上位{MAX_PAIRS_PER_GROUP}件のキャップ適用済)"
    )

    if pairs:
        print("\n✨ 先頭1件のサンプル（※dry-run中は_metadataが表示されます）:")
        print(json.dumps(pairs[0], ensure_ascii=False, indent=2))

    if args.dry_run:
        print("\n🧪 [DRY-RUN] ファイルは書き込みません。")
        return

    os.makedirs(os.path.dirname(args.out_path), exist_ok=True)
    with open(args.out_path, "w", encoding="utf-8") as f:
        for p in pairs:
            # 🛡️ Hugging Face互換性担保: _metadata を出力直前に完全にパージする
            out_rec = {k: v for k, v in p.items() if k != "_metadata"}
            f.write(json.dumps(out_rec, ensure_ascii=False) + "\n")

    print(f"\n💾 書き出し完了（_metadataパージ済・HF完全互換） → {args.out_path}")


if __name__ == "__main__":
    main()
