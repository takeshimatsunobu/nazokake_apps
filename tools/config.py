"""
tools/config.py
=================
tools/*.py が依存する環境変数を、起動時に一括でスキーマ検証するFail-Fastな設定モジュール
(IaCアプローチ)。プロジェクトルートの .env を読み込みつつ、実際のOS環境変数を優先する
標準的な優先順位(pydantic-settingsの既定動作)で値を解決する。

従来は tools/benchmark/run_benchmark.py のように、個々のスクリプトが
    os.environ["OLLAMA_HOST"] = "127.0.0.1:11434"
という無検証のワークアラウンドを個別にハードコードしていた。これは値が既に妥当かどうかを
一切確認せず常に上書きしてしまうため、本当の設定ミス(例: サーバーのbindアドレス
"0.0.0.0"をクライアント接続先として誤設定している)を検知できず、問題を静かに
隠蔽していた。本モジュールはこれを廃止し、以下に一元化する:
  1. Pydantic Settingsでスキーマを定義し、必須キーの欠損や不正な形式を起動直後に検出する。
  2. 検証・正規化済みの値だけを、ここ一箇所でのみ os.environ へ反映する
     (ChatOllama等のサードパーティライブラリがos.environを直接読むため)。

使い方:
    from tools.config import settings
    print(settings.ollama_host)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from pydantic import SecretStr, field_validator  # noqa: E402
from pydantic_settings import BaseSettings, SettingsConfigDict  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# アプリ本体(apps/evaluator/backend、ローカルLLM推論)とMLOps(tools/mlops_pipeline_*.py、
# 学習/評価)が限られたVRAM(8GB)を排他的に使うためのグローバルファイルロック。
# どちらが起動していても、このパスへのfilelock.FileLockで調停する(OSレベルの
# ロックのため、プロセスが異常終了してもOSが自動的に解放する)。
VRAM_LOCK_PATH = PROJECT_ROOT / ".vram.lock"

# クライアント接続先としては到達不能な「サーバーのbind用アドレス」。OLLAMA_HOSTに
# これが設定されていた場合、フォーマット自体は妥当でも実質的に不正な設定とみなす。
_WILDCARD_HOSTS = {"0.0.0.0", "::", "*", ""}


class ToolsSettings(BaseSettings):
    """tools/*.py 全体で共有する環境変数スキーマ。"""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Ollamaクライアント(ChatOllama等)の接続先。多くの環境では未設定のままでも
    # Ollamaの既定値(127.0.0.1:11434)で問題なく動作するため、デフォルト値を持たせる
    # (「必須キー」として無条件に必須化すると、素の未設定環境まで壊してしまうため)。
    # 一方、値が明示的に設定されているにもかかわらずクライアントとして使えない形式
    # (例: サーバーのbindアドレスである"0.0.0.0")の場合はFail-Fastで拒否する。
    ollama_host: str = "http://127.0.0.1:11434"

    @field_validator("ollama_host")
    @classmethod
    def _validate_ollama_host(cls, v: str) -> str:
        raw = (v or "").strip()
        if not raw:
            raise ValueError("OLLAMA_HOSTが空文字列です。")

        candidate = raw if "://" in raw else f"http://{raw}"
        parsed = urlsplit(candidate)
        if not parsed.hostname:
            raise ValueError(
                f"OLLAMA_HOSTから有効なホスト名を取り出せませんでした: {raw!r}"
            )
        if parsed.hostname in _WILDCARD_HOSTS:
            raise ValueError(
                f"OLLAMA_HOST={raw!r} はサーバーのbind用アドレスであり、クライアントの"
                "接続先としては使用できません。127.0.0.1 等の到達可能な具体的ホストを"
                "指定してください(環境変数OLLAMA_HOSTを修正するか、.envで上書きしてください。"
                "なお環境変数は.envより優先されるため、OSレベルで設定済みの場合はそちら側の"
                "修正が必要です)。"
            )
        return candidate

    # CTOエスカレーション(tools/agent_graph.py)の閾値。Qwenが自己申告する
    # confidence_scoreがこの値を下回るか、requires_escalation=Trueを申告した場合に
    # クラウド上位モデル(Claude)へエスカレーションする。ハードコードせずここで
    # 環境変数(.env)経由の上書きを許可する。
    escalation_confidence_threshold: float = 0.8

    # logprobsベースのエントロピー計算による、より厳密な不確実性推定への拡張余地を
    # 予約するフィーチャートグル。現時点ではQwen自身が申告するconfidence_score
    # (JSON出力内のフィールド)のみを信頼度の根拠として使用し、このトグル自体は
    # 常にFalseで未実装・未使用(将来ここにOllamaのlogprobs対応を組み込む場合に
    # 備えた明示的な無効化フラグ)。
    enable_logprobs_entropy: bool = False

    # MLOpsパイプライン(tools/mlops_pipeline_agent.py)の定量評価ゲートにおける
    # Code Complexity(ASTノード数)増加率の許容上限。以前はモジュール内の
    # マジックナンバー(MAX_COMPLEXITY_GROWTH_RATE = 0.10)としてハードコードされて
    # いたが、閾値の調整に毎回コード変更を要してしまうため、環境変数(.env)経由の
    # 上書きを許可するここへ外部化する。
    quality_gate_complexity_max: float = 0.10

    # 異常終了時・定量評価ゲート不合格時にDiscord/Slack等へ通知するWebhook URL。
    # 【絶対制約】この値はログや例外メッセージに平文で出現し得ないよう、
    # pydantic.SecretStrで保持する(str(settings)やrepr(settings)でも
    # "**********"にマスクされ、実際のURL文字列はget_secret_value()を明示的に
    # 呼んだ場合のみ取得できる)。未設定(None)の場合、通知機能自体を無効化する。
    alert_webhook_url: SecretStr | None = None

    # tools/mlops_trigger.py(イベント駆動のワンショットMLOps起動トリガー)の
    # 発火閾値。以前はモジュール内のマジックナンバー(NAZO_THRESHOLD = 500 /
    # AGENT_THRESHOLD = 50)としてハードコードされていたが、運用中の調整に毎回
    # コード変更を要してしまうため、環境変数(.env)経由の上書きを許可するここへ
    # 外部化する。
    mlops_trigger_nazo_threshold: int = 500
    mlops_trigger_agent_threshold: int = 50

    # 【instructions/173→174: ステートレスな条件評価への移行に伴うクールダウン
    # (実行間隔制御)】なぞかけ候補件数(count_nazo_candidates)・Nazo-Agent成功
    # 修復ログ件数(count_agent_success_logs)はいずれも学習済みでも減らない単調
    # 増加の生カウントであり、「学習済みフラグ」が存在しない。ステートレスな生
    # カウント比較(前回トリガー時点の記憶を持たない)へ移行した代わりに、DB
    # (nazokake_core.database.TriggerStateORM)のlast_completed_at(直前に
    # パイプラインが正常完了した時刻)がこの時間内であれば、閾値超過中でも新規の
    # 起動を見送ることで多重発火を防ぐ。以前はローカルファイル
    # (MLOPS_PIPELINE_LOCK_PATHのmtime)への状態依存だったが、instructions/174で
    # このアンチパターンを排除し、DBへ完全移行した。
    #
    # 【排他制御(Mutex)とクールダウンの分離への追補修正】完了時に単に「解放」する
    # だけではクールダウンそのものが破壊され次回評価が即座に再起動してしまうため、
    # クールダウンの起点はstatusの遷移から独立したlast_completed_atのみに限定する
    # (mlops_trigger_stale_after_hoursとは役割が異なる別の設定)。
    mlops_trigger_cooldown_hours: float = 24.0

    # 【排他制御(Mutex)側: ハードクラッシュ前提の自己修復(ゾンビ回収)】
    # VRAM 8GB環境でのOOM Killer/SIGKILLによる強制終了はtry/except/finallyが一切
    # 機能しないため、trigger_stateのstatus="running"がDBに永久に残るゾンビ状態を
    # 引き起こしうる。last_triggered_at(直前にclaimした時刻)からこの時間を超えて
    # 経過している場合、前回のプロセスが異常死したと決定論的にみなしclaimを自動的に
    # パージする(実際の学習所要時間より十分長く、無期限ブロックよりは遥かに短い
    # 値を想定)。mlops_trigger_cooldown_hours(実行間隔制御)とは独立した、
    # 排他制御(Mutex)専用の設定。
    #
    # 【instructions/177: エフェメラルVM化に伴う見直し】以前はtools/mlops_trigger.py
    # 自身がローカルプロセスをfire-and-forgetでキックし即座に終了する設計だったため、
    # 2.0時間で十分「実際の学習所要時間より十分長い」値だった。エフェメラルVM化後は
    # このトリガー自身がtools/deploy/run_ephemeral_pipeline.ps1(VM起動→SSH開通待ち→
    # 転送→パイプライン同期実行→VM停止)の完了を丸ごとawaitで待機する設計に変わり、
    # 現実的な所要時間(VM起動+実際の学習+VM停止)は2時間を容易に超え得る。この値が
    # 短すぎると、1回目の実行が正当にまだ稼働中であるにもかかわらず2回目の評価が
    # ゾンビ回収と誤判定してclaimを再奪取し、同一VM上で学習が二重に走ってしまう
    # (無期限ブロックのリスクより実害が大きい)ため、安全側に倒して延長する。
    mlops_trigger_stale_after_hours: float = 12.0

    # Epic 2: Nazo-Agentの本番稼働(権限委譲)を客観的に判定する6次元定量評価ゲート
    # (tools/benchmark/run_benchmark.py の evaluate_6d_quality_gate())の各次元の閾値。
    # quality_gate_complexity_max は既存フィールドを共用する。
    quality_gate_success_rate_min: float = 0.90
    quality_gate_regression_rate_max: float = 0.0
    quality_gate_max_retries: int = 3
    quality_gate_allowed_blast_radius: int = 0

    # 第6の指標「時間対品質パリティ」(instructions/145)。CTOエスカレーション
    # (Claude、高コスト・低速)が発生したfixtureについて、そのlatency_msが
    # Qwenのみで解決したfixture群の平均latency_msの何倍まで許容するかの上限。
    # CTOエスカレーションが1件も発生していない場合はこの次元自体が対象外(N/A)となり
    # 合否には影響しない(tools/benchmark/run_benchmark.py.evaluate_6d_quality_gate())。
    quality_gate_time_to_quality_parity_max: float = 3.0

    # 【instructions/182: フライホイールの防弾化(シャドウモード)】データフライホイール
    # (tools/mlops_trigger.py・tools/nazo_agent.py・tools/agent_graph.pyの自己修復/
    # 学習ループ)を完全無人で回すにあたり、Agentの出力品質監視
    # (nazokake_core.quality_circuit_breaker)が実戦で十分に検証されるまでの段階的
    # 始動措置。有効な間は、これらのモジュールの実際のDB更新(トリガー状態のclaim・
    # エフェメラルVMキック)・Gitコミット(適用)を一切行わず、実行されたはずの内容を
    # tools/shadow_mode.py経由でログ/検証用ファイル(tools/shadow_mode_log.jsonl)へ
    # 出力するのみに留める。当面はこれを既定で有効(True)とし、無効化する場合のみ
    # 環境変数SHADOW_MODE=falseで明示的に上書きする。
    shadow_mode: bool = True

    # 【instructions/261: ポート管理のSSoT化】ローカル開発用APIサーバー(run_api.ps1が
    # 起動するuvicorn main:app)の正規リッスンポート。以前はrun_api.ps1・
    # tools/nazo_agent.py・フロントエンドの複数JSファイルに7800という値が個別に
    # ハードコードされており、出自不明な別ポート(instructions/260で発見した8095の
    # ゾンビuvicorn等)との区別がつかない構成ドリフトの温床となっていた。
    api_dev_port: int = 7800

    # ローカル開発用フロントエンド静的サーバー(dev_server.py)の正規リッスンポート。
    # api_dev_port と同じ理由でSSoT化するが、本設定を実際に参照するようリファクタ
    # 済みなのは現時点でrun_api.ps1のみ(instructions/261 Step 2の対象範囲)。
    frontend_dev_port: int = 7300


def load_settings() -> ToolsSettings:
    """設定を読み込み検証する。失敗時は意味のあるメッセージを出してFail-Fastする。"""
    try:
        loaded = ToolsSettings()
    except Exception as e:
        print(f"🚨 [Fail-Fast] 環境変数の検証に失敗しました:\n{e}", file=sys.stderr)
        sys.exit(1)

    # ChatOllama(langchain-ollama)/ollamaパッケージはOLLAMA_HOSTをos.environから
    # 直接読み取るため、検証・正規化済みの値をこの一箇所でだけos.environへ反映する。
    os.environ["OLLAMA_HOST"] = loaded.ollama_host
    return loaded


settings = load_settings()
