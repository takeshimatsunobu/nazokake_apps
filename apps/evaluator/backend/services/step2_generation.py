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
(api/routers/generate.py)は odai/step1/persona/db を渡すだけでよい。

【Phase3で async化】services/step1_estimation.pyと同じ理由(コスト計装の追加を
機に、asyncio.to_thread経由のパターンへ揃えてイベントループのブロッキングも
同時に解消する)。

【Phase5/6】管理コクピット(Ⅱペイン)で①🏆Goldenと評価されFew-shot採用が確定した
実例を、nazokake_core.fewshots.get_fewshot_pool()経由でルートAのプロンプトへ
注入する(D)。ルートB(異常入力への逆手エンタメ応答)は真面目な創作例を模倣する
性質のタスクではないため対象外とする。
"""
from __future__ import annotations

import asyncio
import json
import os

from google import genai
from google.genai.types import GenerateContentConfig, ThinkingConfig, ThinkingLevel
from nazokake_core.env_config import get_gemini_api_key
from nazokake_core.fewshots import get_fewshot_pool, sample_fewshot_examples

from models.persona_schemas import Step1Result
from services.cost_logging import log_step_cost

# persona_feature_plan_v3.md §3.2: thinking_levelはGeminiのみ適用対象
# (temperatureはELYZA用のフィールドだが、このサービスはGemini一本のため未使用)。
_THINKING_LEVEL_MAP = {
    "low": ThinkingLevel.LOW,
    "medium": ThinkingLevel.MEDIUM,
    "high": ThinkingLevel.HIGH,
}


def _compose_persona_prompt(persona: dict) -> str:
    """persona設定辞書からキャラクター設定文字列を組み立てる。

    ビルトイン({name, prompt}の2キーのみ)は従来どおりpromptだけを使い、
    既存の生成挙動を一切変えない。マイペルソナ(PersonaSettingsInputの全項目)は
    first_person/speech_style/tone/favorite_topics/tabooを追記し、口調・トーン
    設定が実際の生成へ反映されるようにする(persona_feature_plan_v3.md Phase5、
    改修要件2「マイペルソナの設定を生成パイプラインへ正しく渡す」)。
    """
    base = persona.get("prompt", "")
    extra_lines = []
    if persona.get("first_person"):
        extra_lines.append(f"一人称: {persona['first_person']}")
    if persona.get("speech_style"):
        extra_lines.append(f"語尾・口調の癖: {persona['speech_style']}")
    if persona.get("tone"):
        extra_lines.append(f"全体の雰囲気: {persona['tone']}")
    if persona.get("favorite_topics"):
        extra_lines.append(f"得意なお題のジャンル: {'、'.join(persona['favorite_topics'])}")
    if persona.get("taboo"):
        extra_lines.append(f"できるだけ避ける話題: {'、'.join(persona['taboo'])}")
    if not extra_lines:
        return base
    return base + "\n【追加の人物設定】\n" + "\n".join(extra_lines)

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
{fewshot_block}"""

# ルートB(is_valid_input=false): 異常入力(無意味な文字列)を逆手に取ったエンタメ
# 応答。「わかりません」系の謝罪・エラー発言は禁止(is_valid_for_training=falseで
# 学習データからは除外されるため、品質より「必ず何か返す」ことを優先する設計)。
_ROUTE_B_SYSTEM_INSTRUCTION_TEMPLATE = """\
あなたはプロのなぞかけ師です。以下の【語り手キャラクター設定】になりきって対応してください。
【語り手キャラクター設定】: {persona_prompt}
ユーザーから辞書にはない無意味な文字列（または理解不能な言葉）がお題として提示されました。これを逆手に取り、「音の響き」だけを強引に利用するか、「意味不明な言葉をお題に出してくる相手」を軽くイジるなぞかけを生成してください。
【厳格な制約】: 「意味がわかりません」とマジメに謝罪したり、システムエラーを返す発言は禁止です。必ずエンターテイメントとして見事に切り返し、キャラクター性を爆発させてください。\
"""


async def _build_fewshot_block(db) -> str:
    """管理コクピットで①🏆Goldenと評価されFew-shot採用が確定した実例を、
    毎回ランダムに3件抽出してプロンプト注入用のブロック文字列へ組み立てる。

    get_fewshot_pool()はTTLキャッシュ済みだが内部でFirestore I/Oが発生し得るため、
    イベントループをブロックしないようasyncio.to_threadへ委譲する
    (nazokake_core.personas.get_personas()と同じ呼び出し規約)。
    """
    pool = await asyncio.to_thread(get_fewshot_pool, db)
    picks = sample_fewshot_examples(pool, k=3)
    if not picks:
        return ""
    lines = [json.dumps(d, ensure_ascii=False, separators=(",", ":")) for d in picks]
    return (
        "\n【お手本（管理コクピットで①🏆Goldenと評価された実例 / 毎回ランダムに3件抽出）】\n"
        "下記は過去に高く評価された「お題→解き→こころ」の実例。この発想の質と構造を参考にせよ:\n"
        + "\n".join(lines)
        + "\n"
    )


async def generate_step2(
    odai: str,
    step1: Step1Result,
    persona: dict,
    db=None,
    model_id: str | None = None,
) -> tuple[str, str, str, str, str]:
    """odai/Step1結果/ペルソナ辞書からルートA/Bを判定し、なぞかけを生成する。

    戻り値: (route, toku, kokoro, nazokake_text, 使用モデルID)。
    route は "A"(is_valid_input=true、通常系) または "B"(is_valid_input=false、
    異常入力系。呼び出し元はis_valid_for_training=falseとして保存すること)。
    """
    model_id = model_id or os.environ.get("STEP2_MODEL", "gemini-2.5-flash")
    persona_prompt = _compose_persona_prompt(persona)
    thinking_level = _THINKING_LEVEL_MAP.get(persona.get("thinking_level", ""))

    if step1.is_valid_input:
        route = "A"
        fewshot_block = await _build_fewshot_block(db)
        system_instruction = _ROUTE_A_SYSTEM_INSTRUCTION_TEMPLATE.format(
            persona_prompt=persona_prompt,
            step1_json=json.dumps(step1.model_dump(), ensure_ascii=False),
            fewshot_block=fewshot_block,
        )
    else:
        route = "B"
        system_instruction = _ROUTE_B_SYSTEM_INSTRUCTION_TEMPLATE.format(
            persona_prompt=persona_prompt,
        )

    def _call():
        client = genai.Client(api_key=get_gemini_api_key(), http_options={"timeout": 60000})
        config_kwargs = dict(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=_STEP2_SCHEMA_DICT,
            temperature=0.9,
        )
        # マイペルソナのthinking_level(§3.2、Geminiのみ)が指定されていれば反映する。
        # ビルトインpersonaにはthinking_levelキーが無いため、既存の挙動は変わらない。
        if thinking_level is not None:
            config_kwargs["thinking_config"] = ThinkingConfig(thinking_level=thinking_level)
        return client.models.generate_content(
            model=model_id,
            contents=odai,
            config=GenerateContentConfig(**config_kwargs),
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
