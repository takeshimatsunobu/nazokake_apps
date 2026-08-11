"""
services/step2_generation.py
==============================
Step2(ルートA/B分岐・ペルソナ反映生成)のLLM呼び出し。

既存の apps/evaluator/backend/services/generation.py と同じ構造化出力パターン
(response_mime_type="application/json" + response_schema、google-genai SDK)を
踏襲する。システムプロンプトはgoogle-genai SDKの system_instruction フィールド
(GenerateContentConfig)で分離し、contentsにはお題の生テキストのみを渡す
(services/step1_estimation.pyと同じ方針)。

ルートA/Bの分岐判定(step1.is_valid_input)はこの関数の内部で行う。呼び出し元
(api/routers/generate.py)は odai/step1/persona を渡すだけでよい。

【Phase3で async化】services/step1_estimation.pyと同じ理由(コスト計装の追加を
機に、asyncio.to_thread経由のパターンへ揃えてイベントループのブロッキングも
同時に解消する)。
"""
from __future__ import annotations

import asyncio
import json
import os

from google import genai
from google.genai.types import GenerateContentConfig
from nazokake_core.env_config import get_gemini_api_key

from models.schemas import Step1Result
from services.cost_logging import log_step_cost

_STEP2_SCHEMA_DICT = {
    "type": "OBJECT",
    "properties": {
        "toku": {"type": "STRING"},
        "kokoro": {"type": "STRING"},
        "nazokake_text": {"type": "STRING"},
    },
    "required": ["toku", "kokoro", "nazokake_text"],
}

# ルートA(is_valid_input=true): 通常の生成。背景文脈データ(Step1の7属性)は
# あくまで「かけ言葉のシチュエーション構築」の参考情報に留め、ペルソナの
# キャラクター性を最優先させる。
_ROUTE_A_SYSTEM_INSTRUCTION_TEMPLATE = """\
あなたはプロのなぞかけ師です。以下の【語り手キャラクター設定】になりきって、なぞかけを生成してください。
【語り手キャラクター設定】: {persona_prompt}
【背景文脈データ】: {step1_json}
【厳格なトーン制約】: 背景文脈データは「かけ言葉」のシチュエーション構築にのみ使用し、特定の界隈や若者言葉への過度な迎合（媚び）は厳禁です。ただし、あなたが演じるキャラクターの口調や属性（ギャル、ビジネス用語等）は絶対優先とし、相手が誰であっても自分のキャラクター性を爆発させてください。\
"""

# ルートB(is_valid_input=false): 異常入力(無意味な文字列)を逆手に取ったエンタメ
# 応答。「わかりません」系の謝罪・エラー発言は禁止(is_valid_for_training=falseで
# 学習データからは除外されるため、品質より「必ず何か返す」ことを優先する設計)。
_ROUTE_B_SYSTEM_INSTRUCTION_TEMPLATE = """\
あなたはプロのなぞかけ師です。以下の【語り手キャラクター設定】になりきって対応してください。
【語り手キャラクター設定】: {persona_prompt}
ユーザーから辞書にはない無意味な文字列（または理解不能な言葉）がお題として提示されました。これを逆手に取り、「音の響き」だけを強引に利用するか、「意味不明な言葉をお題に出してくる相手」を軽くイジるなぞかけを生成してください。
【厳格な制約】: 「意味がわかりません」とマジメに謝罪したり、システムエラーを返す発言は禁止です。必ずエンターテイメントとして見事に切り返し、キャラクター性を爆発させてください。\
"""


async def generate_step2(
    odai: str,
    step1: Step1Result,
    persona: dict,
    model_id: str | None = None,
) -> tuple[str, str, str, str, str]:
    """odai/Step1結果/ペルソナ辞書からルートA/Bを判定し、なぞかけを生成する。

    戻り値: (route, toku, kokoro, nazokake_text, 使用モデルID)。
    route は "A"(is_valid_input=true、通常系) または "B"(is_valid_input=false、
    異常入力系。呼び出し元はis_valid_for_training=falseとして保存すること)。
    """
    model_id = model_id or os.environ.get("STEP2_MODEL", "gemini-2.5-flash")
    persona_prompt = persona["prompt"]

    if step1.is_valid_input:
        route = "A"
        system_instruction = _ROUTE_A_SYSTEM_INSTRUCTION_TEMPLATE.format(
            persona_prompt=persona_prompt,
            step1_json=json.dumps(step1.model_dump(), ensure_ascii=False),
        )
    else:
        route = "B"
        system_instruction = _ROUTE_B_SYSTEM_INSTRUCTION_TEMPLATE.format(
            persona_prompt=persona_prompt,
        )

    def _call():
        client = genai.Client(api_key=get_gemini_api_key(), http_options={"timeout": 60000})
        return client.models.generate_content(
            model=model_id,
            contents=odai,
            config=GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=_STEP2_SCHEMA_DICT,
                temperature=0.9,
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
    return route, raw["toku"], raw["kokoro"], raw["nazokake_text"], model_id
