from .schemas import TargetContext, WarheadForgingResult, CommissarAuditResult, WarheadCOA
from .prompts import (
    PHASE1_CONTEXT_EXTRACTION_PROMPT,
    PHASE2_WARHEAD_FORGING_PROMPT,
    COMMISSAR_AUDIT_PROMPT
)

# TODO: 既存のllm/基盤からのインポートパスに後ほど置き換えます
# 例: from llm.client import generate_structured_output

async def analyze_target(target_url: str, thread_text: str) -> TargetContext:
    '''Phase 1: 標的捕捉とコンテキスト抽出'''
    _prompt = f"{PHASE1_CONTEXT_EXTRACTION_PROMPT}\n\n対象テキスト:\n{thread_text}"
    
    # TODO: 既存のLLM基盤を呼び出す処理を組み込む
    # result = await generate_structured_output(prompt, TargetContext, model="claude-sonnet-5")
    # return result

    # --- 結合前のプレースホルダー（モック） ---
    return TargetContext(
        target_url=target_url,
        conflict_structure="見解A（正義）vs 見解B（もう一つの正義）の平行線",
        sunk_cost="過去数十回のレスバに費やした時間と認知資源",
        defensive_pride="「自分の方が論理的・道徳的で優位に立っている」という自己像の死守"
    )

async def run_mdmp_session(context: TargetContext) -> WarheadForgingResult:
    '''Phase 2: 弾頭鋳造 (マルチエージェント幕僚会議)'''
    context_json = context.model_dump_json(indent=2)
    _prompt = f"{PHASE2_WARHEAD_FORGING_PROMPT}\n\n戦場コンテキスト:\n{context_json}"
    
    # TODO: 既存のLLM基盤を呼び出す処理を組み込む
    # result = await generate_structured_output(prompt, WarheadForgingResult, model="claude-sonnet-5")
    # return result

    # --- 結合前のプレースホルダー（モック） ---
    return WarheadForgingResult(
        coas=[
            WarheadCOA(
                coa_type="O-1 徹甲弾",
                nazokake_text="SNSの終わらない議論とかけて、休日の二度寝と解く。その心は、どちらも『無意味と分かっていても気持ちよくてやめられない』でしょう。私なんか昨日も夕方まで寝てしまい、絶望のまま月曜を迎えました。",
                tactical_intent="正義感の裏にある『快楽』を指摘しつつ、自身のどうしようもない休日を晒して脱力させる",
                damage_prediction="反発の余地をなくし、一時的な沈黙を呼ぶ"
            ),
            WarheadCOA(
                coa_type="O-2 EMP弾",
                nazokake_text="白熱する論争とかけて、熱々のたこ焼きと解く。その心は、どちらも『外はカリカリ、中はドロドロ』でしょう。私の胃腸はもうドロドロで何も受け付けませんが。",
                tactical_intent="論理の対立を物理的な温度と食感にすり替える",
                damage_prediction="論点がズレて毒気を抜かれる"
            ),
            WarheadCOA(
                coa_type="O-3 照明弾",
                nazokake_text="見えない敵との戦いとかけて、ダイエット器具と解く。その心は、どちらも『買った（勝った）つもりで満足しているだけ』でしょう。我が家の腹筋ローラーも今は立派なドアストッパーです。",
                tactical_intent="自己満足というメタ視座の提供",
                damage_prediction="サンクコストへの気づき"
            )
        ]
    )

async def audit_warhead(warhead_text: str) -> CommissarAuditResult:
    '''Phase 3: 動機監査 (コミッサールAI / G-7)'''
    _prompt = f"{COMMISSAR_AUDIT_PROMPT}\n\n対象弾頭:\n{warhead_text}"
    
    # TODO: 既存のLLM基盤を呼び出す処理を組み込む
    # result = await generate_structured_output(prompt, CommissarAuditResult, model="gemma4:12b")
    # return result

    # --- 結合前のプレースホルダー（モック） ---
    return CommissarAuditResult(
        preachiness_score=0.45,
        warning_message="⚠️警告：指揮官、この弾頭には相手をコントロールしようとする教導欲求がわずかに検知されました。決めるのは彼らです。あなたはただの道化であることをお忘れなく。"
    )
