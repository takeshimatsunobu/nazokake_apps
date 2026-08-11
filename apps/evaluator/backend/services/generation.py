"""なぞかけ生成エンジン（ai_service.py から分離）。

Gemini（主軸・即時）と ELYZA（おまけ・遅延）の生成、CoTフラットスキーマ、
および Dynamic Few-Shot（固定の完全例1件 ＋ プールからランダム抽出 N 件）を担う。
JSON抽出・検証は output_parser へ委譲する。
"""

import asyncio

# VRAM 8GB防弾用セマフォ（Ollamaへの同時リクエストを1つに強制制限）
_OLLAMA_SEMAPHORE = asyncio.Semaphore(1)

import json
import os
import sys
import threading

# Windowsの既定コンソールはcp932であり、print()で絵文字(📚等)を出力すると
# UnicodeEncodeErrorが発生する。本モジュールは_load_fewshot_pool()をモジュール
# 読み込み時点で即時実行するため、この例外はアプリ全体の起動クラッシュに直結する
# (uvicorn起動時、api.routers importチェーン経由でこのファイルがimportされた
# 瞬間に発生)。tools/run_migrations.pyと同じ対策(stdout/stderrをUTF-8へ
# reconfigure)をここでも適用する。TextIOWrapperでない場合(pipe等)はreconfigure
# 自体が無いため呼ばない。
if sys.platform == "win32":
    import io

    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")

import filelock
import httpx
from firebase_admin import firestore
from google import genai
from google.genai.types import GenerateContentConfig
from loguru import logger

from nazokake_core.env_config import get_gemini_api_key

from .evaluation import get_dynamic_correction_prompt
from .output_parser import _extract_json_dict, _valid_nazokake

# MLOps(tools/mlops_pipeline_nazo.py / tools/mlops_pipeline_agent.py)とVRAM(8GB)を
# 排他的に共有するためのグローバルファイルロック。apps/evaluator は独立してデプロイ
# される別リポジトリのため、リポジトリルートの tools/config.py には直接依存しない
# (本番Cloud Run環境にtools/は存在せず、ローカルLLM自体も呼ばれないため無関係)。
# ローカル開発時にMLOpsパイプラインと同一ファイルを指すよう、run_api.ps1が設定する
# 環境変数VRAM_LOCK_PATHを優先し、未設定時はカレントディレクトリ基準の相対パスへ
# フォールバックする(その場合はMLOps側と一致しないため排他制御は効かないが、
# ローカルにOllama/GPUが無い本番環境ではこのロック自体が使われないため無害)。
_VRAM_LOCK_PATH = os.environ.get("VRAM_LOCK_PATH", ".vram.lock")


class _ReentrantVramLock:
    """VRAM排他ロックを「同一プロセス内では再入可能」にするラッパー。

    【実機ログで確認したセルフロックアウト】workers/ondemand_elyza_worker.py の
    best-of-N構成(1ジョブ内でgenerate_via_llmjp()をN=3回concurrent実行)では、
    毎回 filelock.FileLock(...) を新規に生成していたため、同一プロセス内の
    3つの並行呼び出しがそれぞれ独立したロックオブジェクトとしてOSレベルの
    同じロックファイルを奪い合っていた。timeout=0(フェイルファスト)のため、
    1つ目が取得した直後に2つ目・3つ目が「自分自身が(別インスタンス経由で)
    取得したロック」に阻まれて即座にGeminiへフォールバックしていた
    (外部のMLOpsパイプラインは無関係で、完全な自己ブロック)。

    本来このロックで排他したいのは「別プロセス(MLOpsパイプライン等)との同時
    VRAMアクセス」であり、同一プロセス内でのOllama呼び出し自体は既に
    _OLLAMA_SEMAPHORE(Semaphore(1))が直列化を保証している。そのため、同一
    プロセス内では参照カウント方式で再入を許可し、他プロセスが実際に保持して
    いる場合のみフェイルファストでNoneを返す(timeout=0のセマンティクスは
    「他プロセス」に対してのみ維持する)。
    """

    def __init__(self, path: str):
        self._path = path
        self._guard = threading.Lock()
        self._file_lock: filelock.FileLock | None = None
        self._refcount = 0

    def try_acquire(self) -> bool:
        """成功時True。既にこのプロセスが保持していれば再入として即成功する。
        他プロセスが実際に保持している場合のみFalse(リトライしない)。
        """
        with self._guard:
            if self._file_lock is not None:
                self._refcount += 1
                return True
            lock = filelock.FileLock(self._path, timeout=0)
            try:
                lock.acquire()
            except filelock.Timeout:
                return False
            self._file_lock = lock
            self._refcount = 1
            return True

    def release(self) -> None:
        """参照カウントが0になった時点で初めて実際のOSロックを解放する。
        対応するtry_acquireが無い誤呼び出しは安全側で無視する。
        """
        with self._guard:
            if self._file_lock is None:
                return
            self._refcount -= 1
            if self._refcount <= 0:
                self._file_lock.release()
                self._file_lock = None
                self._refcount = 0


_vram_lock = _ReentrantVramLock(_VRAM_LOCK_PATH)


def _try_acquire_vram_lock() -> bool:
    """VRAM排他ロックの非ブロッキング取得を試みる(OSレベルのファイルロック、
    プロセス間。同一プロセス内は_ReentrantVramLockにより再入可能)。

    MLOpsパイプラインが同じロックファイルを保持している間は即座に諦め、ローカルLLM
    (Ollama)呼び出しを行わずFalseを返す(呼び出し元はクラウドAPIへフォールバック
    する)。取得できた場合は呼び出し元が使用後に必ず_vram_lock.release()すること。
    """
    return _vram_lock.try_acquire()


# ============================================================
# 生成エンジン定義（11軸を狙う創作ルーブリック ＋ 構造化CoTスキーマ）
# ============================================================

# 改善A: 評価11軸に正面から対応させる「創作指針」。生成用システムプロンプトに注入する。
GEN_GUIDANCE = """あなたの作品は「謎掛け学術振興会」の11軸で絶対評価されます。下記を強く意識して創作してください。

【高得点を狙う創作指針】
◆意外性(S_sur): お題と解きは「遠く」結びつける。近い同義語・安直な連想だけの解きは禁止。
◆存在論的深み(S_ontology)【名作の鍵】: 「そのこころ」は表面的な形・音の一致で終わらせず、両者に共通する“本質・存在意義”を突くこと。ここが最重要。
◆技巧(S_tech): 同音異義語・掛詞・ダブルミーニングを織り込む（ただし単なるダジャレで終わらせない）。
◆納得感(S_emo): 種明かしの瞬間に「なるほど！」というカタルシスが生まれる論理にする。
◆リズム/韻律(S_rhy, S_prosody): 七五調や母音の響きを意識し、音読して心地よく仕上げる。
◆映像/五感/共感覚(S_visual, S_sensory, S_cm): 可能なら鮮烈な情景・五感・感覚の交差を一筆加える。
◆文化(S_cultural): 日本文化・常識・あるあるの共通認識を巧みに使う。
◆自然さ(S_nat): 全体を流麗で自然な日本語に仕上げる。"""

# 改善B: 思考連鎖(CoT)を「フラットな第一階層」で出力させる生成スキーマ。
# ELYZA 8B など小型モデルの認知負荷を下げるため入れ子(thinking)を廃し、全キーを第一階層に並べる。
# CoT→answer の順序は propertyOrdering で担保（連想/掛詞/本質/意外性 を考えてから toku/kokoro を決める）。
# 下流(result.toku/kokoro 利用・UIのhint表示)との後方互換は _finalize がフラット出力から
# hint と thinking を再構築することで維持する。
GEN_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "associations": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "お題からの多角的な連想ワードの羅列",
        },
        "kakekotoba": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "同音異義語・掛詞・ダブルミーニングの候補 (S_tech)",
        },
        "shared_essence": {
            "type": "STRING",
            "description": "お題と解きに共通する“本質・存在意義” (S_ontology)",
        },
        "surprise_check": {
            "type": "STRING",
            "description": "お題と解きが遠い概念かの意外性の自己評価 (S_sur)",
        },
        "toku": {"type": "STRING", "description": "解きとなる10文字以内の短い名詞"},
        "kokoro": {"type": "STRING", "description": "共通点・オチの文章（そのこころ）"},
        "persona_comment": {
            "type": "STRING",
            "description": "ペルソナの語り口・キャラクターになりきった一言コメント（エンタメ演出用、任意）",
        },
    },
    "required": [
        "associations",
        "kakekotoba",
        "shared_essence",
        "surprise_check",
        "toku",
        "kokoro",
    ],
    "propertyOrdering": [
        "associations",
        "kakekotoba",
        "shared_essence",
        "surprise_check",
        "toku",
        "kokoro",
        "persona_comment",
    ],
}

# システムプロンプトに埋め込むJSON出力例（フラット構造。f-stringの波括弧エスケープを避けるため別定義で連結）。
# persona_comment は required に含めない(空文字でも許容)ため、古いFew-shot/ELYZA出力が
# このキーを欠いても _valid_nazokake / Result のバリデーションを壊さない。
_GEN_JSON_TEMPLATE = (
    '{"associations": ["..."], "kakekotoba": ["..."], '
    '"shared_essence": "...", "surprise_check": "...", '
    '"toku": "解きの単語(10文字以内)", "kokoro": "オチの文章", '
    '"persona_comment": "ペルソナになりきった一言コメント"}'
)

# Few-shot のお手本（フラット構造）。ダジャレ単発で終わらせず、本質的共通点まで踏み込む良例を1件提示する。
# ※これは「出力フォーマット固定用」の不変の完全例。多様性は _sample_fewshot_block() のランダム抽出で担保する。
_GEN_FEWSHOT_EXAMPLE = (
    "お題: サウナ\n"
    '{"associations": ["熱い", "汗", "整う", "水風呂", "我慢"], '
    '"kakekotoba": ["整う（サウナで整う / 時計の針が整う）"], '
    '"shared_essence": "どちらも正しい状態にリセットされることで価値が出る。", '
    '"surprise_check": "サウナと時計は物理的に全く異なる概念であり、意外性が高い。", '
    '"toku": "時計", '
    '"kokoro": "どちらも、はり（針・張り）がととのうでしょう。"}'
)

# ============================================================
# Dynamic Few-Shot（Phase5/6: nazokake_core.fewshots へ統一）。
# ============================================================
# 【Phase5/6での変更】従来はモジュール読み込み時に外部JSON(nazokake_fewshot.json)
# を静的ロードし、POST /admin/feedbacks/refresh-fewshot Webhookでプロセス内
# メモリの_FEWSHOT_POOLを手動更新する方式だった(プロセス間でメモリを共有できない
# ため、複数ワーカー構成では更新が全プロセスへ伝播しない欠陥があった)。
# apps/persona_router側の生成へも同一のGoldenデータを注入する(D)にあたり、
# 管理コクピットの「⭐ Few-shot採用」(review_status=="golden" + タグ確定)を起点に
# Firestore(nazokake_fewshots)へPushし、両サービスが
# nazokake_core.fewshots.get_fewshot_pool()(TTLキャッシュ、300秒)経由で
# 同じデータを読む構成へ一本化した。
#
# 【トレードオフ】旧_FEWSHOT_POOLの各エントリはCoT全工程
# (associations/kakekotoba/shared_essence/surprise_check)を含む重量級の辞書
# だったが、nazokake_fewshotsは apps/persona_router::step2_generation.py の
# 出力スキーマに合わせた軽量な辞書(odai/toku/kokoro/nazokake_text)のみを保持する。
# このためGEN_SCHEMA(本モジュール)が要求するCoTフィールドの「お手本」は
# 静的な_GEN_FEWSHOT_EXAMPLE(1件、不変)のみとなり、動的抽出分の思考プロセス例は
# 提示されなくなる(プロンプト品質へのトレードオフとして要監視)。
from nazokake_core.fewshots import get_fewshot_pool, sample_fewshot_examples


async def _sample_fewshot_block() -> str:
    """共有Few-shotプール(nazokake_core.fewshots)から毎回【必ず3件】抽出し、
    辞書を「1行JSON」に量子化して埋め込む（Dynamic Few-Shot）。

    プールが空/3件未満でも安全（k はプール件数で上限クランプ、0件なら空文字）。
    get_fewshot_pool()はTTLキャッシュ済みだが内部でFirestore I/Oが発生し得るため、
    イベントループをブロックしないようasyncio.to_threadへ委譲する。
    """
    pool = await asyncio.to_thread(get_fewshot_pool)
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


def _chat_completion_local_sync(
    url,
    system_prompt,
    user_prompt,
    max_tokens,
    temperature,
    json_mode,
    model,
):
    import os

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.9,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    # Cloudflare Zero Trust の VIPパスを環境変数から "名前（キー）" を指定して正しく取得
    headers = {
        "ngrok-skip-browser-warning": "true",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    cf_id = os.environ.get("CF_CLIENT_ID")
    cf_secret = os.environ.get("CF_CLIENT_SECRET")

    if cf_id and cf_secret:
        headers["CF-Access-Client-Id"] = cf_id
        headers["CF-Access-Client-Secret"] = cf_secret

    # 接続フェイルファスト: サーバダウン時は connect=5s で即諦め、読み取り(生成)には read_timeout の猶予を確保する
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
        res = client.post(url, json=payload, headers=headers)
        res.raise_for_status()
        return (
            res.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )


async def chat_completion_local(
    url,
    system_prompt,
    user_prompt,
    max_tokens=256,
    temperature=0.8,
    json_mode=False,
    model="gemma",
    read_timeout=35.0,
):
    if not url:
        raise ValueError("URL未設定")
    # 【実機計測に基づく修正】httpx.AsyncClient(イベントループネイティブな非同期I/O)を
    # このプロセス内で使うと、firebase_admin(Firestore用gRPCクライアント)が同じ
    # プロセス/イベントループに存在する状態でOllamaへの応答が22.8秒までブロート
    # することを実測で確認した(Windows既定のProactorEventLoopとgRPCの相性問題と
    # 推測される。firebase_admin無しの単体実行では同一ペイロードで5.5秒)。同じ
    # プロセス内のGemini呼び出し(generate_via_gemini)が既に同期clientを
    # asyncio.to_threadで別スレッド実行することでこの問題を回避しているのと同じ
    # パターンへ統一し、Ollama呼び出し側もイベントループ非依存の別スレッド実行に
    # 切り替える。実測で22.8秒→7.3秒(約3倍)に短縮した。read_timeoutは現状
    # 未使用(内部でhttpx.Timeout(120.0, connect=5.0)を固定使用)のため触れていない。
    return await asyncio.to_thread(
        _chat_completion_local_sync,
        url,
        system_prompt,
        user_prompt,
        max_tokens,
        temperature,
        json_mode,
        model,
    )


def _summarize_thinking(t) -> str:
    """hint が欠落した場合に、フラットな思考フィールドから人間向け要約を組み立てる。"""
    if not isinstance(t, dict):
        return ""
    parts = []
    if t.get("associations"):
        parts.append("連想: " + "、".join(map(str, t["associations"])))
    if t.get("kakekotoba"):
        parts.append("掛詞候補: " + "、".join(map(str, t["kakekotoba"])))
    if t.get("shared_essence"):
        parts.append("本質的共通点: " + str(t["shared_essence"]))
    if t.get("surprise_check"):
        parts.append("意外性: " + str(t["surprise_check"]))
    return " / ".join(parts)


async def _build_gen_prompts(
    odai: str,
    persona_prompt: str | None = None,
    temperature_override: float | None = None,
):
    """動的設定(temperature/persona)を取得し、CoT生成用の system/user プロンプトを組み立てる。

    お手本は「固定の完全例1件（フォーマット固定）＋プールからのランダム抽出N件（多様性）」のハイブリッド。

    persona_prompt/temperature_override が指定された場合(personas.pyの固定ペルソナを
    ユーザーがリクエストで選択した場合)は、Firestore(system_configs/ai_settings)経由の
    管理者設定デフォルトより優先する。未指定時は従来通りFirestoreの動的設定にフォールバックする。
    """
    db = firestore.client()
    dyn_temp, dyn_persona = 0.8, "あなたは前衛的な天才なぞかけ芸人です。"
    try:
        doc = await asyncio.to_thread(
            db.collection("system_configs").document("ai_settings").get
        )
        if doc.exists:
            d = doc.to_dict()
            dyn_temp = float(d.get("temperature", 0.8))
            dyn_persona = d.get("system_prompt", dyn_persona)
    except Exception as e:
        logger.warning(
            f"⚠️ 動的設定(ai_settings)の取得に失敗、既定値にフォールバック: {e}"
        )

    if persona_prompt is not None:
        dyn_persona = persona_prompt
    if temperature_override is not None:
        dyn_temp = temperature_override

    sys_prompt = (
        f"{dyn_persona}\n\n{GEN_GUIDANCE}\n\n"
        "【思考の手順（フラットなJSONの各キーを上から順に必ず埋める）】\n"
        "1. associations: お題から多角的に連想ワードを羅列する。\n"
        "2. kakekotoba: 同音異義語・掛詞・ダブルミーニングの候補を挙げる（S_tech）。\n"
        "3. shared_essence: お題と解きに共通する“本質・存在意義”を一文で言い切る（S_ontology）。\n"
        "   ※ここが命。単なる音の一致（ダジャレ）で終わらせず、両者が共有する本質まで掘り下げること。\n"
        "4. surprise_check: お題と解きが物理的・概念的に「遠い」かを自己評価する（S_sur）。近ければ却下し選び直す。\n"
        "5. toku: 以上を踏まえ、最も意外で本質を突く解き（短い名詞）を決定する。\n"
        "6. kokoro: 種明かしの一文（そのこころ）。掛詞と本質的共通点が両立する「なるほど」のオチにする。\n"
        "7. persona_comment: 上記のなぞかけを発表した直後、あなたのペルソナのキャラクター・"
        "語り口になりきったまま放つ一言コメント（30〜60文字程度）。\n\n"
        "【絶対制約】toku は必ず10文字以内の短い名詞。\n\n"
        "【お手本（このレベルの思考の深さと出力フォーマットを再現せよ）】\n"
        + _GEN_FEWSHOT_EXAMPLE
        + "\n→ 単なる「整う」のダジャレに留めず、『正しい状態にリセットされる価値』という本質的共通点まで"
        "踏み込んでいる点が高評価のポイント。\n"
        + await _sample_fewshot_block()
    )

    # SRE: 動的プロンプトをDBから取得するステートレスな方法に切り替え
    correction_prompt = await get_dynamic_correction_prompt()
    if correction_prompt:
        sys_prompt += f"\n\n{correction_prompt}"

    sys_prompt += (
        "\n必ず以下のフラットなJSONフォーマット【のみ】で出力してください"
        "（入れ子は禁止。値は例ではなく、お題に対して実際に考えた内容を書く）:\n"
        + _GEN_JSON_TEMPLATE
        + "\n\n※警告（厳守）: 挨拶・説明・前置き・Markdown(```)は一切不要。出力の先頭文字は必ず `{` とし、"
        "純粋なJSONオブジェクトのみを返すこと。\n"
        '文字列は必ず半角ダブルクオート " で囲む（「」『』 等の日本語括弧は使わない）。'
        "配列やオブジェクトの要素に `=`（イコール）を使わず、必ず JSON の正しい構文で記述すること。"
    )

    user_prompt = f"お題「{odai}」でなぞかけを作成し、上記フラットなJSONで出力。"
    return sys_prompt, user_prompt, dyn_temp


async def _log_generation_cost(
    service_type: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    execution_time_sec: float = 0.0,
    success: bool = True,
) -> None:
    """生成コストをsystem_costsへ非同期記録する(失敗してもなぞかけ生成自体は継続する)。

    【Phase1追加】success引数はGemini/Ollama呼び出しそのものが成功したかを表す。
    管理コクピットの「APIエラー率」タイルの集計対象になる。
    """
    try:
        from nazokake_core.cost_calculator import async_log_system_cost

        db = firestore.client()
        await async_log_system_cost(
            db,
            service_type=service_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            execution_time_sec=execution_time_sec,
            success=success,
        )
    except Exception as e:
        print(f"⚠️ コストログ記録に失敗しました(生成処理には影響なし): {e}")


def _finalize(parsed: dict) -> dict:
    """生成結果を正規化（toku を10文字以内にクランプ、hint を補完）して返す。

    新スキーマ(フラット: associations/kakekotoba/shared_essence/surprise_check)を主に扱いつつ、
    旧スキーマ(入れ子 thinking)も後方互換で受理する。返り値の {hint,toku,kokoro,thinking} 形は維持。
    """
    # 防衛的正規化: ELYZAが辞書型で出力した場合、値をリストとして抽出
    if isinstance(parsed.get("associations"), dict):
        parsed["associations"] = list(parsed["associations"].values())
    if isinstance(parsed.get("kakekotoba"), dict):
        parsed["kakekotoba"] = list(parsed["kakekotoba"].values())

    nested = parsed.get("thinking") if isinstance(parsed.get("thinking"), dict) else {}
    # フラット最優先・旧入れ子フォールバックで思考フィールドを集約する。
    thinking = {
        "associations": parsed.get("associations") or nested.get("associations", []),
        "kakekotoba": parsed.get("kakekotoba") or nested.get("kakekotoba", []),
        "shared_essence": parsed.get("shared_essence")
        or nested.get("shared_essence", ""),
        "surprise_check": parsed.get("surprise_check")
        or nested.get("surprise_check", ""),
    }
    toku = str(parsed.get("toku", "") or "").strip()[:10]
    kokoro = str(parsed.get("kokoro", "") or "").strip()
    hint = str(parsed.get("hint", "") or "").strip() or _summarize_thinking(thinking)
    persona_comment = str(parsed.get("persona_comment", "") or "").strip()
    return {
        "hint": hint,
        "toku": toku,
        "kokoro": kokoro,
        "persona_comment": persona_comment,
        "thinking": thinking,
    }


def _is_gemini_auth_error(err: Exception | None) -> bool:
    """APIキーの未設定・不正な形式でよく見られるエラーシグネチャかどうかを判定する。

    google-genaiは認証系の失敗を専用の例外クラスとしては公開しておらず、
    汎用的な例外のメッセージ文字列にしか判別材料がないため、既知のシグネチャで
    判定する(instructions/247: 本番でAPIキーが不正な形式でシークレットに保存
    されており、SDKがOAuth2アクセストークンでの認証にフォールバックして
    401 UNAUTHENTICATED / ACCESS_TOKEN_TYPE_UNSUPPORTED が発生した実例に基づく)。
    """
    if err is None:
        return False
    text = str(err)
    return any(
        marker in text
        for marker in (
            "UNAUTHENTICATED",
            "PERMISSION_DENIED",
            "ACCESS_TOKEN_TYPE_UNSUPPORTED",
            "API key not valid",
            "API_KEY_INVALID",
        )
    )


async def generate_via_gemini(
    odai: str,
    persona_prompt: str | None = None,
    temperature_override: float | None = None,
    model_id: str = "gemini-3.5-flash",
) -> dict:
    """【即時・主軸】Gemini で構造化生成（GEN_SCHEMA＋3回リトライ）。失敗時は例外送出。

    model_id: 既定は現行の主力モデル"gemini-3.5-flash"(既存呼び出し元は無改修で
    従来通り動作する)。緊急対応(自宅ELYZAワーカー回線不調時のGemini Flash Lite
    代打モード、apps/evaluator/backend/api/routers/generate.py::process_elyza参照)
    のため、呼び出し元が任意のGeminiモデルIDを指定できるよう引数化した。
    """
    api_key = get_gemini_api_key() or ""
    if not api_key:
        # 【instructions/247】キー欠落時、Firestoreからのプロンプト構築やGemini SDKの
        # 生の認証エラーで3回リトライを浪費させず即座に失敗させ、フロントエンドに
        # 原因が分かるメッセージを返す。
        raise RuntimeError(
            "Gemini APIキーが設定されていません。管理者に環境変数/シークレット"
            "(GEMINI_API_KEY)の設定をご確認いただくよう連絡してください。"
        )

    sys_prompt, user_prompt, dyn_temp = await _build_gen_prompts(
        odai, persona_prompt, temperature_override
    )
    fallback_model = model_id

    last_err = None
    for attempt in range(3):
        # 💡 SDKバグ回避: 同期クライアントを別スレッドで安全に実行
        def gemini_call():
            client = genai.Client(api_key=api_key)
            return client.models.generate_content(
                model=fallback_model,
                contents=f"{sys_prompt}\n\n{user_prompt}",
                config=GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=GEN_SCHEMA,
                    temperature=dyn_temp,
                ),
            )

        try:
            start_time = asyncio.get_running_loop().time()
            res_create = await asyncio.to_thread(gemini_call)
            elapsed = asyncio.get_running_loop().time() - start_time

            usage = getattr(res_create, "usage_metadata", None)
            await _log_generation_cost(
                fallback_model,
                input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                execution_time_sec=elapsed,
            )

            cand = _extract_json_dict(res_create.text)
            if _valid_nazokake(cand):
                return _finalize(cand)
            print(f"⚠️ Gemini生成の検証失敗 (試行 {attempt + 1}/3)")
        except Exception as e:
            last_err = e
            print(f"⚠️ Gemini生成エラー (試行 {attempt + 1}/3): {e}")
            # 【Phase1】試行が例外で失敗した場合のみsuccess=Falseで計装する
            # (検証失敗で継続するケースは、その後の試行で成功すれば全体としては
            # 成功なので、ここではAPI呼び出し自体が失敗したケースのみを対象にする)。
            await _log_generation_cost(fallback_model, success=False)
        await asyncio.sleep(0.8)

    if _is_gemini_auth_error(last_err):
        # 【instructions/247】キーが設定されてはいるが不正(誤った形式で保存されている
        # 等)な場合、SDKの生の401/OAuthエラー文をそのままユーザーに見せず、原因の
        # 見当がつくメッセージに変換する。詳細は末尾に残し、調査時にログから追える
        # ようにする。
        raise RuntimeError(
            "Gemini APIキーが正しく設定されていません(認証エラー)。"
            f"シークレット/環境変数(GEMINI_API_KEY)の値をご確認ください。詳細: {last_err}"
        )
    raise RuntimeError(f"Gemini生成に3回失敗しました: {last_err}")


# 【1発入魂アルゴリズム(爆速化)】以前はbest-of-N(N=3、workers/ondemand_elyza_worker.py
# 側で並行生成→最高得点選抜)だったが、直列化されたOllama呼び出し(_OLLAMA_SEMAPHORE)の
# 制約下ではN=3ぶんの生成時間が単純に積み上がり、ワーカー全体の応答が遅くなる原因に
# なっていた。1回の生成のみを試み(best-of-1)、出力スキーマ不正時のみここで
# _MAX_OUTPUT_RETRIES回リトライする設計へ変更した。
_MAX_OUTPUT_RETRIES = 3  # 初回1回 + 最大3回リトライ = 最大4回試行。
# VRAM解放のためのクールダウン。以前は2.0秒固定だったが、実測では8Bモデル程度の
# VRAM解放にそこまでの猶予は不要と判断し最小化した。
_VRAM_COOLDOWN_SEC = 0.5


async def generate_via_llmjp(
    odai: str,
    persona_prompt: str | None = None,
    temperature_override: float | None = None,
) -> dict:
    """【1発入魂】ローカル ELYZA(Ollama) で生成。VRAM 8GB防弾仕様。

    接続先・モデルは env で設定: LLMJP_URL / LLMJP_MODEL。
    推論が遅いため read タイムアウトを長め(120s)に取る。
    VRAM枯渇(OOM)を防ぐため、Semaphoreで同時実行数を1に制限し、実行前に
    _VRAM_COOLDOWN_SEC秒のクールダウンを挟む。

    実行前にVRAMグローバルロック(プロセス間、tools/mlops_pipeline_*.pyと共有)の
    非ブロッキング取得を試みる。

    【データ完全性のための変更】以前はVRAMロック取得不可時・出力スキーマ不正が
    リトライを尽くしても解消しない時のいずれも、この関数の内部でGemini生成へ
    黙って差し替えて返していた。これは「ELYZAの出力」として記録されるデータへ
    実際にはGeminiが生成したものが、区別なく混入するデータ完全性の問題を
    引き起こしていた(ELYZAタイムアウト時のGemini Flash Lite代打モード導入に伴い
    是正)。現在はいずれの場合も例外を送出するのみとし、Gemini側への切替が必要な
    場合は呼び出し元(api/routers/generate.py::process_elyza_pinch_hitter等)が
    明示的に行い、llmjp_is_pinch_hitterフラグで正確に記録する設計へ統一した。
    """
    acquired = await asyncio.to_thread(_try_acquire_vram_lock)
    if not acquired:
        raise RuntimeError(
            "VRAMロックを取得できませんでした(他プロセスがVRAMを使用中のため、"
            "ELYZA生成を諦めました)。"
        )

    try:
        async with _OLLAMA_SEMAPHORE:
            print(
                "⏳ [VRAM保護] Ollamaの計算リソースをロックしました。"
                f"VRAM解放のため{_VRAM_COOLDOWN_SEC:.1f}秒間クールダウンします..."
            )
            await asyncio.sleep(_VRAM_COOLDOWN_SEC)

            sys_prompt, user_prompt, dyn_temp = await _build_gen_prompts(
                odai, persona_prompt, temperature_override
            )
            url = os.environ.get(
                "LLMJP_URL", "http://localhost:11434/v1/chat/completions"
            )
            model = os.environ.get("LLMJP_MODEL", "elyza:8b")
            print(f"🏠 [1発入魂] ローカル ELYZA で生成中... ({url}, model={model})")

            # 【出力ブレへの耐性】8Bクラスのローカルモデルは一定確率でJSONスキーマから
            # 外れた出力(必須フィールド欠落)を返す。同じロック保持区間内
            # (再取得不要、安価)で_MAX_OUTPUT_RETRIES回リトライする。
            last_err: Exception | None = None
            for attempt in range(_MAX_OUTPUT_RETRIES + 1):
                start_time = asyncio.get_running_loop().time()
                try:
                    # json_mode=True: Ollama の response_format=json_object で完結したJSONを強制。
                    raw = await chat_completion_local(
                        url,
                        sys_prompt,
                        user_prompt,
                        # persona_comment分の出力が増えるため800まで許容(do_sample相当は
                        # Ollamaがtemperature>0で自動的にサンプリングするため明示指定不要)。
                        max_tokens=800,
                        temperature=dyn_temp,
                        json_mode=True,
                        model=model,
                        read_timeout=120.0,
                    )
                finally:
                    # ローカル実行系はトークン単価ではなく稼働時間ベースの電気代として計上する
                    # (成功/失敗を問わず、VRAMを占有した実時間は発生しているため記録する)。
                    elapsed = asyncio.get_running_loop().time() - start_time
                    await _log_generation_cost("Ollama", execution_time_sec=elapsed)

                cand = _extract_json_dict(raw)
                if _valid_nazokake(cand):
                    print("✅ ELYZA生成に成功！VRAMロックを解除します。")
                    return _finalize(cand)

                last_err = ValueError("ELYZA出力がスキーマ不正でした(必須フィールド欠落)")
                remaining = _MAX_OUTPUT_RETRIES - attempt
                print(
                    f"⚠️ [ELYZA出力不正] {attempt + 1}回目の出力がスキーマ不備(必須フィールド欠落)。"
                    + (f"あと{remaining}回リトライします..." if remaining > 0 else "リトライ上限に達しました。")
                )

            raise RuntimeError(
                f"ELYZA生成が{_MAX_OUTPUT_RETRIES + 1}回とも出力スキーマ不正でした: {last_err}"
            )
    finally:
        await asyncio.to_thread(_vram_lock.release)


async def generate_nazokake(odai: str) -> dict:
    """後方互換ラッパ（test_pipeline 等の既存呼び出し用）。ELYZA → Gemini の順で試す。"""
    try:
        return await generate_via_llmjp(odai)
    except Exception as e:
        print(f"⚠️ ELYZA 生成不可({e})。Gemini へフォールバック。")
    try:
        return await generate_via_gemini(odai)
    except Exception as e:
        return {
            "hint": "JSONパース失敗",
            "toku": "エラー",
            "kokoro": f"生成に失敗しました: {e}",
        }
