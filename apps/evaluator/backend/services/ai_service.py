"""後方互換シム（責務分割の集約点）。

実体は責務別の3モジュールへ移動済み:
  - services.generation     : Gemini/ELYZA 生成・Dynamic Few-Shot
  - services.evaluation     : 11軸評価
  - services.output_parser  : JSON抽出/検証・RAG文脈取得

既存の `from services.ai_service import X` を壊さないため、ここで全公開シンボルを
再エクスポートする。新規コードは各実体モジュールから直接 import すること。
"""

# 生成（相対importで services.* / backend.services.* どちらの読み込み経路でも解決）
from .generation import (  # noqa: F401
    GEN_GUIDANCE,
    GEN_SCHEMA,
    chat_completion_local,
    _summarize_thinking,
    _build_gen_prompts,
    _finalize,
    generate_via_gemini,
    generate_via_llmjp,
    generate_nazokake,
)

# 評価
# 注: _clamp_score / evaluate_and_update_task は evaluation.py の run_evaluation への
# 統合により廃止済み(DB更新は呼び出し側の責務になった)。既存importを壊さないよう
# run_evaluation のみを再エクスポートする。
from .evaluation import (  # noqa: F401
    AXES,
    EVAL_SCHEMA,
    EVAL_RUBRIC_TEMPLATE,
    run_evaluation,
)

# 出力パース・RAG
from .output_parser import (  # noqa: F401
    get_rag_context,
    _first_json_block,
    _salvage_str_field,
    _extract_json_dict,
    _valid_nazokake,
)
