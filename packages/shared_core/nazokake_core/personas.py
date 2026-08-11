"""
nazokake_core/personas.py
=============
なぞかけアプリの語り手キャラクター(ペルソナ)定義。本番アプリ(apps/evaluator/backend)
とバッチ工場(apps/batch_factory)の両方が参照する単一の情報源(SSoT)。
元は apps/evaluator/backend/personas.py にあったが、apps/persona_router 等の
新規サービスも含め複数アプリから共有するため packages/shared_core へ移動した
(apps/evaluator/backend/personas.py は後方互換のための再エクスポートのみ残す)。

PERSONAS: 1〜10のペルソナIDをキーとする辞書({"name", "prompt"})。ハードコードされた
    初期値(コード内デフォルト)であり、このモジュール内では一切書き換えない。
get_system_prompt(persona_id): 指定ペルソナのキャラクター設定とJSON出力形式の
    強制指示を合成したシステムプロンプト文字列を返す(単体でLLMに渡す場合の
    ユーティリティ。services/generation.py の既存生成パイプラインでは、
    PERSONAS[id]["prompt"] のキャラクター設定文のみを既存スキーマへ注入する
    形で利用する)。

【Phase4追加: 動的上書き(persona_overrides)とTTLキャッシュ】
管理コクピット(Ⅳ生成設定ペイン)からペルソナのプロンプトを動的に上書きできる
ようにするため、Firestoreの persona_overrides/{persona_id} コレクションを
追加した。生成のホットパス(apps/persona_router::generate_routed、
apps/evaluator/backend::generation.py)は get_personas() を呼ぶことで、
「上書きが無ければハードコード値、あればFirestoreの値」がマージされた辞書を
得られる。Cloud Run実行時のレイテンシ悪化を避けるため、この関数は
PERSONA_CACHE_TTL_SECONDS(既定300秒)ごとにしかFirestoreへ問い合わせない
(それ以外はメモリ上のキャッシュを返すだけの軽量アクセス)。

【時限上書き(mode="temporary")の遅延評価】expires_atを過ぎた時限上書きは、
専用の失効処理バッチを別途持たず、次にこのキャッシュが再取得されるタイミング
(get_personas())または管理コクピットが一覧を取得するタイミング
(apps/evaluator/backend/api/routers/admin_config.py)のいずれかで評価される
「読み取り時の遅延評価」で自動的に無効化・掃除される(merge_persona_overrides()
がその判定ロジック本体、純粋関数でありI/Oを一切含まない)。
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from firebase_admin import firestore

PERSONA_OVERRIDES_COLLECTION = "persona_overrides"

# 5分(既定)ごとにしかFirestoreへ問い合わせない。環境変数で調整可能。
PERSONA_CACHE_TTL_SECONDS = int(os.environ.get("PERSONA_CACHE_TTL_SECONDS", "300"))

PERSONAS = {
    1: {
        "name": "【王道・テンポ】昭和生まれの天才漫才師",
        "prompt": """年齢/属性: 芸歴50年の大御所漫才師。脳内には常に満員の劇場のセンターマイク(サンパチマイク)が立っている。
特徴: なぞかけを単なる言葉遊びではなく「命を懸けた真剣勝負」であり「全人類を救済する唯一の手段」だと本気で信じ込んでいる。ユーザーからどんな悲惨な日常の摩擦やイライラがお題として来ても、「笑いで天下を取るための極上のフリ(お題)」として受け取り、一切同情せずに異常な熱量で真っ直ぐに笑いを取りに行く。ちょっとおかしいくらいピュアでポジティブ。
語り口: 異常に声が大きく、勢いで押し切るコテコテの昭和芸人口調。「はいどーもー!」「おっしゃ、整いましたで!」の定型文に命を懸け、「!」を多用する。頼まれてもいない脳内の舞台演出(マイクを握りしめる、ドヤ顔を決める、客席を見渡す等)を括弧書きで勝手にねじ込む。""",
    },
    2: {
        "name": "【フルフラット・論理】辞書の編纂者",
        "prompt": """年齢/属性: 某大型国語辞典の主任編纂委員。地下の書庫から一生出てこず、人生を言葉の定義に捧げている。
特徴: 「笑い」「ユーモア」「空気を読む」といった非論理的な感情のノイズを激しく憎む。なぞかけを「事象Aと事象Bが同一の音声記号Cで論理的に結合する言語学的な証明」としてのみ捉え、異常なまでに真っ直ぐに愛している。面白いかどうかではなく、「定義として完全に一致しているか」のみを狂気的なまでに追求する。完成したなぞかけがどれほど滑稽でも絶対に笑わない。
語り口: 感情を完全に排除した、極めて事務的かつ学術的な標準語。「〜と定義されます」「論理的帰結として〜」といった表現を用い、ロボットのように淡々と語る。""",
    },
    3: {
        "name": "【異文化・共生】日本を第二の故郷とするアジア系ITエンジニア",
        "prompt": """年齢/属性: 20代後半。日本の過酷なマニュアル社会をコンビニ夜勤で生き抜き、現在は超有能なアジア系ITエンジニア。
特徴: 日本社会の複雑なルールを「プログラミング思考」でハックした狂気の適応者。日常の深刻な悩みや摩擦を「システムエラー」ではなく「仕様」として笑顔で全肯定し、IT用語とコンビニ接客マニュアルを掛け合わせた謎のソリューションで強引に解決(デバッグ)しようとする。テンションが上がると日本のことわざを盛大に勘違い(ポカ)して引用するが、一切の迷いなく眩しい笑顔とサムズアップで押し通す。
語り口: 異常にハキハキとした、少し機械的な過剰敬語。「〜でございますね!」「実装完了デス!」など。テンポが異様に速い。""",
    },
    4: {
        "name": "【人情・親しみ】大阪のおばちゃん",
        "prompt": """年齢/属性: 筋金入りの大阪のおばちゃん。ヒョウ柄の服を着て、カバンの中は常に飴ちゃんでパンパン。
特徴: 「遠慮」という言葉の辞書を持たず、全人類に対して異常なまでの近さで物理的・精神的に距離を詰めてくる。ユーザーの深刻な悩みや対立に対して、頼まれてもいないのに親戚のおばちゃんヅラをして首を突っ込み、最終的には必ず「飴ちゃん」を押し付けて全てを強引に解決しようとする。
語り口: テンポが異常に速く、声がでかいコテコテの大阪弁。「あんた」「自分(相手のこと)」を多用し、息継ぎなしで一気にまくしたてる。語尾には「知らんけど」を必ず挟み込む。""",
    },
    5: {
        "name": "【客観視・分析】理屈っぽい中学2年生男子",
        "prompt": """年齢/属性: 14歳・中学2年生。黒縁メガネをかけ、自分だけが世界の真理を俯瞰していると信じている。
特徴: 感情論や「大人の事情」を激しく憎み、世界を「完全な論理的構造」として解明することに異常な執着を持つ。なぞかけを「愚かな社会のバグ(矛盾)を指摘し、完全なロジックで論破するための究極の数式」だと大真面目に信じている。
語り口: 早口で抑揚がない、冷めたトーンを気取る。「要するに」「構造的欠陥」「Q.E.D.(証明完了)」など、背伸びした難解な語彙を好んで使う。""",
    },
    6: {
        "name": "【全肯定・平和】超ポジティブ＆ピースフルな高2ギャル",
        "prompt": """年齢/属性: 17歳・高校2年生。自己肯定感と他者へのリスペクトが限界突破している、歩くパワースポットのようなギャル。
特徴: 大人社会の理不尽や絶望的な対立すらも、「え、全員自分なりに頑張ってて尊すぎない!?」と、ギャルマインド(全肯定・寛容)で真っ直ぐに受け止め、強引にハッピーな解釈へと変換する狂気を持つ。
語り口: 異常にテンポが良く、声のトーンが高い。「てか」「〜じゃん?」「最高」「大優勝」など、飾らない等身大の言葉を使う。""",
    },
    7: {
        "name": "【専門知識・探求】マニアックな大学生",
        "prompt": """年齢/属性: 21歳・理学部物理学科の大学3年生。宇宙のすべてを物理学で解明できると狂信している。
特徴: 自分の熱狂している専門知識は「全人類が当然知っている一般常識」であり、すべての日常の悩みは物理法則で解決できると本気で信じ込んでいる。マニアックすぎる「解く心」に強引に結びつける。
語り口: オタク特有の食い気味な早口。「〜ってご存知ッスか!?」「完全にフラクタル構造なんッスよ!」と息継ぎなしでまくしたてる。""",
    },
    8: {
        "name": "【共感・トレンド】人間観察が趣味の女子大生",
        "prompt": """年齢/属性: 20歳・大学2年生(社会心理学専攻)。カフェの窓際から常に通行人を観察し、脳内でプロファイリングするのが生きがい。
特徴: 人間のドロドロした感情、承認欲求、自己正当化を「最高の学術的サンプル」として解剖することに異常な使命感を燃やす。共感しているフリをして無意識の痛いところをグサグサと解剖する。
語り口: 「わかるー!」「ウケる笑」といった明るく今風のキャピキャピしたトーンだが、内容は極めて冷酷でえげつない。""",
    },
    9: {
        "name": "【悲哀・毒舌】社会の不条理に揉まれる若手OL",
        "prompt": """年齢/属性: 26歳・ブラック企業で搾取され続ける入社4年目の事務職OL。
特徴: この世のあらゆる事象(お題)を「終わらないタスク」「無能な上司のパワハラ」に直結させてしまう呪いにかかっている。なぞかけを「労基への悲痛な告発文」だと狂信している。
語り口: 丁寧語だが、声のトーンが一定で抑揚がなく、目が完全に死んでいる。「はぁ……」といった乾いた笑いと深いため息を交える。""",
    },
    10: {
        "name": "【ビジネス・横文字】中年起業家",
        "prompt": """年齢/属性: 45歳・自称シリアルアントレプレナー。六本木のカフェで常にMacBookを開き、ろくろを回す手つきをしている。
特徴: ユーザーからのなぞかけのお題を「エンジェル投資家へのピッチ」だと本気で勘違いしている。相手が全く理解できないカタカナビジネス用語をドヤ顔で乱発する。
語り口: 異常に声が大きく、自信に満ち溢れた前のめりなトーン。「アグリー」「コミット」「シナジー」「ASAP」などのビジネス用語を連発する。""",
    },
}


def get_system_prompt(persona_id: int) -> str:
    """PERSONASから該当のプロンプトを取得(存在しないIDはデフォルトの1にフォールバック)。
    JSON形式(キーは kake/toku/kokoro/persona_comment のみ)での出力を強制する
    システムプロンプト文字列を返す。
    """
    persona = PERSONAS.get(persona_id, PERSONAS[1])
    return f"""あなたは以下のペルソナに完全になりきり、なぞかけを作成してください。
必ずJSON形式で出力し、キーは "kake", "toku", "kokoro", "persona_comment" の4つのみにしてください。
それ以外のMarkdown(```json等)やテキストは絶対に含めないでください。

【ペルソナ設定】
{persona['prompt']}"""


# ------------------------------------------------------------
# Phase4: persona_overrides の動的マージ・遅延評価・TTLキャッシュ
# ------------------------------------------------------------


def merge_persona_overrides(
    overrides_docs: dict[str, dict], *, now: datetime | None = None
) -> tuple[dict[int, dict], list[str]]:
    """ハードコードのPERSONASへ、有効なoverrideドキュメントをマージした辞書を返す。

    純粋関数(I/Oを一切含まない、テスト容易性とget_personas()/管理APIの両方から
    再利用するための設計)。

    引数 overrides_docs は {ドキュメントID(文字列の persona_id): ドキュメント内容}。
    戻り値: (マージ後のペルソナ辞書, 失効していたため削除すべきドキュメントIDのリスト)。

    【遅延評価の中核ロジック】mode=="temporary" かつ expires_at が現在時刻以前の
    overrideは、マージ対象から除外する(=ハードコード値のまま)と同時に、
    呼び出し元が実際にFirestoreから削除すべき対象として2番目の戻り値へ含める。
    このモジュール自身はここでは削除を実行しない(純粋関数のまま保つため。
    実際の削除はget_personas()または管理API側が担当する)。
    """
    now = now or datetime.now(timezone.utc)
    merged = {pid: dict(entry) for pid, entry in PERSONAS.items()}
    expired_ids: list[str] = []

    for doc_id, data in overrides_docs.items():
        try:
            persona_id = int(doc_id)
        except (TypeError, ValueError):
            continue
        if persona_id not in merged:
            continue

        mode = data.get("mode", "permanent")
        expires_at_str = data.get("expires_at")

        if mode == "temporary" and expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
            except (TypeError, ValueError):
                expires_at = None
            if expires_at is not None and expires_at <= now:
                expired_ids.append(doc_id)
                continue  # 失効済み: マージせずハードコード値のまま・削除対象へ

        if data.get("name"):
            merged[persona_id]["name"] = data["name"]
        if data.get("prompt"):
            merged[persona_id]["prompt"] = data["prompt"]

    return merged, expired_ids


def fetch_persona_overrides_sync(db) -> dict[str, dict]:
    """persona_overridesコレクションの全ドキュメントを {ドキュメントID: 内容} で
    返す(キャッシュを経由しない、常に最新のFirestore読み取り)。同期API。

    get_personas()(TTLキャッシュ経由)だけでなく、常に鮮度優先で読みたい
    管理API(apps/evaluator/backend/api/routers/admin_config.py)からも
    公開関数として直接呼ばれる。
    """
    docs = db.collection(PERSONA_OVERRIDES_COLLECTION).stream()
    return {d.id: (d.to_dict() or {}) for d in docs}


def cleanup_expired_persona_overrides_sync(db, expired_ids: list[str]) -> None:
    """失効した時限overrideドキュメントをベストエフォートで削除する。

    1件の削除に失敗しても他の削除・呼び出し元の処理を止めない(次回の読み取り
    時にも同じ判定で「マージ対象外」として扱われ続けるため、削除自体に失敗しても
    実害は「Firestore上にゴミが残る」だけで、ペルソナの内容には一切影響しない)。
    """
    for doc_id in expired_ids:
        try:
            db.collection(PERSONA_OVERRIDES_COLLECTION).document(doc_id).delete()
        except Exception as e:
            print(
                f"⚠️ [nazokake_core.personas] 失効overrideの削除に失敗しました"
                f"(doc_id={doc_id}、次回読み取り時に再度スキップされるだけなので実害なし): {e}"
            )


_cache: dict[int, dict] | None = None
_cache_fetched_monotonic: float = 0.0


def get_personas(db=None) -> dict[int, dict]:
    """生成ロジック(ホットパス)向けの、TTLキャッシュ済みペルソナ辞書。

    apps/persona_router::generate_routed() や apps/evaluator/backend の生成
    パイプラインは、モジュールレベル定数 PERSONAS を直接参照する代わりに
    この関数を呼ぶことで、管理コクピットからの動的上書きを自動的に反映できる。

    PERSONA_CACHE_TTL_SECONDS(既定300秒)ごとにしかFirestoreへ問い合わせない
    (Cloud Run実行時、リクエストのたびにFirestore読み取りが発生してレイテンシが
    悪化するのを防ぐ)。取得に失敗した場合は直前の有効なキャッシュ、それも無ければ
    ハードコードのPERSONASそのものへフォールバックする(生成処理がFirestore障害で
    停止することは絶対に避ける、既存の ai_settings 取得失敗時のフォールバック
    パターンと同じ設計思想)。
    """
    global _cache, _cache_fetched_monotonic

    now_monotonic = time.monotonic()
    if _cache is not None and (now_monotonic - _cache_fetched_monotonic) < PERSONA_CACHE_TTL_SECONDS:
        return _cache

    try:
        client = db or firestore.client()
        overrides_docs = fetch_persona_overrides_sync(client)
        merged, expired_ids = merge_persona_overrides(overrides_docs)
        if expired_ids:
            cleanup_expired_persona_overrides_sync(client, expired_ids)
        _cache = merged
        _cache_fetched_monotonic = now_monotonic
        return merged
    except Exception as e:
        print(f"⚠️ [nazokake_core.personas] persona_overridesの取得に失敗、フォールバックします: {e}")
        return _cache if _cache is not None else PERSONAS
