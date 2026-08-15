"""
services/step1_estimation.py
==============================
Step1(お題の7属性推定)のLLM呼び出し。

既存の apps/evaluator/backend/services/generation.py と同じ構造化出力パターン
(response_mime_type="application/json" + response_schema、google-genai SDK)を
踏襲する。システムプロンプトはgoogle-genai SDKの system_instruction フィールド
(GenerateContentConfig)で分離し、contentsにはお題の生テキストのみを渡す
(既存コードベースの一部(llm_client.py等)はsystem+userを文字列連結しているが、
Step1は「お題の言葉の性質のみに焦点を当てる」という要件が明確なため、モデルに
役割を強く意識させられるsystem_instructionを使う方が適切と判断)。

【Phase3で async化】以前はこの関数が同期のままasync def generate_routed()から
直接(awaitせず)呼ばれており、Gemini SDKの同期I/O待ち時間だけイベントループを
ブロックしていた。コスト計装(services.cost_logging.log_step_cost、非同期)を
呼ぶ必要が生じたことを機に、apps/evaluator/backend/services/evaluation.pyと同じ
asyncio.to_thread経由のパターンへ揃え、ブロッキングも同時に解消する。
"""
from __future__ import annotations

import asyncio
import json
import os

from google import genai
from google.genai.types import GenerateContentConfig
from nazokake_core.env_config import get_gemini_api_key

from models.persona_schemas import Step1Result
from services.cost_logging import log_step_cost

_STEP1_SCHEMA_DICT = {
    "type": "OBJECT",
    "properties": {
        "is_valid_input": {"type": "BOOLEAN"},
        "domain_category": {
            "type": "STRING",
            "enum": ["school", "work", "hobby", "daily_life", "general_unknown"],
        },
        "vocabulary_difficulty": {
            "type": "STRING",
            "enum": ["easy", "standard", "advanced"],
        },
        "slang_level": {
            "type": "STRING",
            "enum": ["none", "youth_slang", "jargon"],
        },
        "wordplay_flexibility": {
            "type": "STRING",
            "enum": ["high", "medium", "low"],
        },
        "topic_scale": {
            "type": "STRING",
            "enum": ["personal", "social", "global"],
        },
        "is_seasonal": {"type": "BOOLEAN"},
    },
    "required": [
        "is_valid_input",
        "domain_category",
        "vocabulary_difficulty",
        "slang_level",
        "wordplay_flexibility",
        "topic_scale",
        "is_seasonal",
    ],
}

_STEP1_SYSTEM_INSTRUCTION = """\
あなたは「なぞかけ生成アプリ」の入力判定アシスタントです。ユーザーから入力される短いテキスト（お題）を分析し、指定されたJSONスキーマに従って7つの属性に分類してください。
【重要なルール】
1. 辞書的な意味を持たない無意味な文字列や、デタラメな文字の羅列（例：「あぐりー」「あああ」など）が入力された場合は、必ず is_valid_input を false にしてください。
2. is_valid_input が false の場合でも、他のフィールドは推測されるデフォルト値を埋めて出力してください。
3. 巨大な知識検索や説明は一切不要です。入力された文字列そのものの「言葉の性質」のみに焦点を当ててください。\
"""


async def estimate_step1(odai: str, model_id: str | None = None) -> tuple[Step1Result, str]:
    """お題のみからStep1Resultを推定する。戻り値は (結果, 使用モデルID)。

    model_id 未指定時は環境変数 STEP1_MODEL を使う(推奨: Flash / Flash-Lite。
    分類タスクであり大規模な推論力を要さないため、コスト最適なモデルを既定とする)。
    """
    model_id = model_id or os.environ.get("STEP1_MODEL", "gemini-2.5-flash")

    def _call():
        client = genai.Client(api_key=get_gemini_api_key(), http_options={"timeout": 60000})
        return client.models.generate_content(
            model=model_id,
            contents=odai,
            config=GenerateContentConfig(
                system_instruction=_STEP1_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=_STEP1_SCHEMA_DICT,
                temperature=0.1,
            ),
        )

    start_time = asyncio.get_running_loop().time()
    try:
        res = await asyncio.to_thread(_call)
    except Exception:
        elapsed = asyncio.get_running_loop().time() - start_time
        await log_step_cost(model_id, execution_time_sec=elapsed, success=False)
        raise
    elapsed = asyncio.get_running_loop().time() - start_time

    usage = getattr(res, "usage_metadata", None)
    await log_step_cost(
        model_id,
        input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
        output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        execution_time_sec=elapsed,
        success=True,
    )

    raw = res.parsed if isinstance(res.parsed, dict) else json.loads(res.text or "{}")
    return Step1Result.model_validate(raw), model_id
