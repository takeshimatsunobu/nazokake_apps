# Nazo-kake System: Project Context & SSoT

## 1. System Overview & Mission
- **Project Goal:** なぞかけ自動評価・生成システムの構築、および「Nazo-Agent」による自律開発支援パイプラインの確立。
- **Ultimate Vision:** 最新の技術要件とシステムの実行エラーを日次で自律監査し、コードの修正・テスト・デプロイまでを人間の介入なしに完遂する完全自律型パイプラインの実現。
- **Current Phase:** 完全自律化に向けた「厳密監視フェーズ（初期3ヶ月）」。AIによるテスト陳腐化判定と自動PR作成（Human-in-the-Loop）を組み込み、監視と評価の基盤を構築・検証中。

## 2. System Architecture & Subsystems
- **Deployment Topology (Local-First):** FastAPI（バックエンド）、フロントエンド、バッチ工場（`apps/batch_factory`）のすべてをローカルPC上で稼働させることを基本方針とする。外部（スマホ等）からのアクセスが必要な場合に限り、Cloudflare Tunnel経由でローカルのフロントエンド/APIを外部公開するハイブリッド構成を取り、常時稼働のクラウドサーバーには依存しない。
- **Y-Shaped Data Pipeline Architecture:** 【instructions/264でパス表記を実態に修正、詳細は3節】
  - **自律・実験的フロー:** `apps/batch_factory/batch/` がバックグラウンドで自律的にお題を抽出し、実験的な生成・評価・データ蓄積を非同期で行う(`workers/`は別途、8.2節の名前付き例外専用)。
  - **ユーザー駆動フロー:** `apps/evaluator/backend/api/routers/*` がユーザーからの同期的なリクエスト（オンデマンド生成・評価）を受け付ける。
  - **共通収束:** 双方の入り口から入ったデータは、共通の生成・評価パイプラインを通過し、単一の「ローカルSSoT DB」へと収束する（クラウド側のFirestoreへは非同期の一方向バックアップ同期のみが行われる。詳細は8.2節）。
- **Nazo-Agent Autonomous Pipeline:**
  - Pytestの実行結果を起点とする決定論的エスカレーション機構（Pytest -> Gemma -> Qwen -> Claude）。
  - 客観的ファクト抽出と、テストコード保護を内包する自己修復・評価ループ。

## 3. Directory Structure & Strict Boundaries
本システムでは、自律エージェントが安全にコードを修正できるよう、インフラストラクチャとドメインロジックの境界を厳格に分離する。
【instructions/262→264: 構成ドリフト監査により、当初想定していたトップレベルディレクトリ`llm/`・`evaluation/`・`interfaces/`は実際には作られておらず、責務が別の実パスへ実装されていた事実が判明した。以下は実態に合わせて修正済み。】

- **LLM通信・スキーマ層 (Infrastructure: LLM Integration & Schemas)**
  - **実体パス:** `apps/batch_factory/batch/llm_client.py`(Ollama通信)、`apps/evaluator/backend/services/{ai_service.py, generation.py}`(Gemini/ELYZA通信)、`tools/{agent_graph.py, nazo_agent.py}`(Claude通信)。単一の`llm/`ディレクトリへは集約されていない。
  - **責務:** 外部LLM（Ollama, Gemini, Claude）との通信基盤、およびPydanticを用いた入出力の構造化（スキーマ定義、`packages/shared_core/nazokake_core/schemas.py`）。
  - **制約（Agent Sandbox）:** プロンプト等、ドメイン固有のテキストをこれら通信コードへ無秩序にハードコードしない。Criticによる自律的な修正の対象外（原則禁止）とする。
- **評価ドメイン層 (Domain: Evaluation Pipeline & Prompts)**
  - **実体パス:** `apps/evaluator/backend/services/evaluation.py`(採点ルーブリック`EVAL_RUBRIC_TEMPLATE`・軸定義`AXES`・スコアリングロジック`run_evaluation`本体)。旧記述の`evaluation/prompts.py`は実在しない架空パスだったため訂正する。
  - **責務:** なぞかけの品質評価、スコアリングのルール定義、客観的ファクト抽出。
  - **制約（Agent Sandbox）:** Criticはコンテンツ内容や評価基準自体（`evaluation.py`内の`AXES`/`EVAL_RUBRIC_TEMPLATE`等）には干渉しない。
- **`workers/` (Infrastructure: 名前付き例外専用領域 — オンデマンドELYZAジョブキュー)**
  - **実体:** `workers/ondemand_elyza_worker.py`の1ファイルのみ。8.2節の一方向同期原則に対する、名前付き・限定的な例外(instructions/250)を実行するための専用領域であり、非同期バッチワーカー全般の置き場所ではない。
  - **量産バッチパイプラインの実体:** 辞書・トレンド抽出等の実験的・量産型バッチ処理(排他制御・DLQ含む)は`apps/batch_factory/batch/`(14ファイル構成)が担う。`workers/`とは責務・スケールの異なる別モジュールである点に注意。
- **`interfaces/`という名前のディレクトリは存在しない。** リアルタイムなユーザー入力の受付・エンドユーザー駆動のエンドポイントおよび同期制御は`apps/evaluator/backend/api/routers/*`(`generate.py`が中心)として実装されている。
- **`tools/` (Infrastructure & Security: Agent Local Automation 全般)**
  - **責務(実態に合わせて拡張):** エージェントがローカル環境を操作するための防弾化されたセキュアI/O・AST解析・静的型チェックに加え、LLMクライアント(`agent_graph.py`/`nazo_agent.py`)、MLOps/学習パイプライン(`mlops_*.py`/`train_*.py`)、デプロイ運用(`deploy/`/`deploy_poll_daemon.py`/`manage_local_processes.ps1`)、データセット抽出(`extract_*.py`)まで包含する、エージェント関連ローカル自動化ツール全般の置き場所である。

## 4. Core Mechanisms & Completed Features (Done)
構造化出力とフェイルセーフ: PydanticとTool CallingによるJSON構造化出力の強制、および自己修正ループ（Self-Correction）と枯渇時のデッドレター出力。

セキュリティとコンプライアンス: PII（個人識別情報）のマスキング・サニタイズ処理。

パフォーマンスとスケーラビリティ: APIコストゼロ環境でのN=100規模ローカルストレステストの完走と、pytest-testmon + pytest-xdist による選択的・並列テスト実行機構の導入。

Criticトリアージ (Human-in-the-Loop): SSoTの動的注入によるテスト陳腐化判定と、自動PRドラフト生成機構の実装。

セマンティック差分検証: ast.AnnAssign やタプルアンパック等を含む網羅的なASTノード消失検知。

## 5. Engineering Standards & Strict Constraints
本システムの開発および自律修復において、以下の規約を例外なく適用する。

- **I/O & Encoding Strictness:** すべてのファイル操作において、`encoding="utf-8"` および `errors="strict"` を完全に明示する。
- **Safe File Operations:** ファイルの書き込みは「一時ファイル → リネーム」のアトミック書き込みとし、`shutil.copymode` を用いてパーミッション・メタデータを確実に保持する。
- **Semantic Diff Validation:** AST（抽象構文木）解析により、コード修正時の意図しないロジック破壊を検知・ブロックする。

## 6. Autonomous Repair & Escalation Loop
- **3層防弾エスカレーション (3-Tier Escalation):** 1. `Gemma 12b` がエラーログを解析し原因を特定（現場監督）。
  2. `Qwen Coder` がローカルでAST書き換え・コード修正を実行（職人）。
  3. `Claude Sonnet` はQwenが解決できない複雑なバグの最終エスカレーション先（CTO）。
- **PR Draft Generation (Human-in-the-Loop):** 厳密監視フェーズ中、エージェントは直接メインブランチにコミットせず、本SSoTを動的に読み込んだ上でアーキテクチャ上の妥当性を明記したプルリクエスト（PR）のドラフトを作成する。

## 7. Active Backlog & Roadmap (To Do)
[Priority High] 課題 I (✅ 完了 (Done)): tools/ 内におけるアトミック書き込みの完全化（一時ファイル生成・shutil.copystat によるパーミッション/mtime/atime等メタデータの保持・filelockによる排他制御・os.replaceによる不可分なファイル置換、tools/ast_modifier.py の _atomic_write_text）。

[Priority Medium] 課題 L: OpenTelemetry等を活用したLLMOps専用トレース基盤（LangSmith, Datadog等）へのログ統合。

[Priority Medium] 課題 P: DPO/SFT 完全自動パイプラインの構築（データ抽出からモデル評価まで）。
【instructions/262→264で解像度を修正】データ抽出側(`extract_dpo_data.py`等によるTier A/B選定ロジック)は本番品質まで成熟済み。一方、学習・モデル評価の自動化(`tools/train_local_model.py`)は自認する通り依然モック実装(実学習コードはコメントアウトのまま、2秒スリープの疑似成功ログで代替)であり、両段階の成熟度には大きな差がある。「To Do」は学習・評価自動化の未着手を指す。

## 8. Detailed Module Specifications (モジュール詳細仕様)

### 8.1. Domain Layer (Evaluation Pipeline) Requirements
【instructions/264: `evaluation/`はトップレベルディレクトリとして実在せず、実体は`apps/evaluator/backend/services/evaluation.py`である。以下のパス表記を実態に修正済み(3節参照)。】
- **概要:** なぞかけの「評価ロジック」と「プロンプト」をカプセル化する純粋なドメイン層。状態を持たない（Stateless）。
- **`apps/evaluator/backend/services/evaluation.py`の`run_evaluation`:** LLMを呼び出しスコアリングを実行する。DBへの保存は行わない。赤ペン先生による修正データに対しても、全く同一のロジックで再評価を行う。
- **`apps/evaluator/backend/services/evaluation.py`の`EVAL_RUBRIC_TEMPLATE`/`AXES`:** 評価基準をLLMに指示するためのテキストテンプレートと11軸のスコアリングルーブリック定義。
- **【絶対制約】:** エージェントの役割はシステムエラーの修復（SRE/QAの責務）に限定される。なぞかけのコンテンツ内容や `apps/evaluator/backend/services/evaluation.py` 内の`EVAL_RUBRIC_TEMPLATE`/`AXES`等の評価基準テキストを自律的に書き換えることは厳格に禁止する。

### 8.2. Infrastructure Layer (`workers/`, `apps/evaluator/backend/api/routers/`, & Database) Requirements
【instructions/264: `interfaces/`はトップレベルディレクトリとして実在しない。実体は`apps/evaluator/backend/api/routers/*`である。`workers/`の責務も8.2節後段の名前付き例外専用領域へ縮小済み(3節参照)。】
- **モジュール分離:**
  - **`apps/batch_factory/batch/`:** 実験的・量産型の非同期ワーカー。辞書やトレンドからお題を抽出し、MLデータの継続的な拡充を担当(`workers/`ではない。詳細は3節)。
  - **`apps/evaluator/backend/api/routers/*`:** ユーザー指定のお題でのリアルタイム生成、または評価リクエストを同期的に処理するエンドポイント。
- **Local SSoTモデル (絶対的正データストア):** ローカルDB（SQLite等）を単一の絶対的な正（Single Source of Truth）と定義する。すべての新規データ生成・更新は必ずローカルDBに対してのみ行う。ドキュメント契約は `packages/shared_core/nazokake_core/schemas.py` の `NazokakeItem` としてPydanticで凍結し、`doc_id`/`odai`/`nazokake_text`/`scores`/`s_total`等の必須フィールドを保証する。
- **Firestoreの役割 (読み取り専用レプリカ/バックアップ):** Firestoreはクラウド上の「読み取り専用レプリカ」および「バックアップ」としてのみ機能させる。クラウド側からの新規書き込みは一切禁止し、ローカルDB→Firestoreへの一方向同期のみを許可することで、スプリットブレイン問題を物理的に排除する。
- **【instructions/250: 名前付き・限定的な例外】オンデマンドELYZAジョブキュー:** 上記の一方向同期原則に対する、意図的かつ範囲を限定した唯一の例外。Cloud Run本番環境にはローカルOllama/ELYZAへの直接到達経路が(トンネル接続時を除き)存在しないため、なぞかけの"おまけ"(ELYZA)生成をFirestore経由の非同期ジョブとしてローカルワーカー(`workers/ondemand_elyza_worker.py`)へ委譲する。
  - Cloud Run側はこの例外においても直接Firestoreへ書き込まない。「pending」の合図はCloud Run自身のローカルSQLite(`POST /generate`の通常upsert)へ書くだけであり、既存の一方向同期(`sync_once`)がそれを間接的にFirestoreへ伝播させる。
  - `workers/ondemand_elyza_worker.py` だけが、Firestoreへの書き込み権限を持つ第二の書き手として明示的に許可される。ただし対象は次の狭いフィールド集合に厳格に限定する: `elyza_job_status` / `elyza_job_locked_at` / `elyza_job_retry_count` / `llmjp_status` / `result_llmjp` / `nazokake_text_llmjp` / `scores_llmjp` / `s_total_llmjp` / `overall_llmjp` / `axis_comments_llmjp`。`status`/`eval_status`/`result`/`result_gemini`/`scores`/`message`等のGemini・主系フィールドには一切書き込まない(`doc_ref.update()`によるフィールド単位の更新のみを用い、ドキュメント全体を置換する`set()`は使わない)。
  - この例外を許容してもなお二重書き込みによる破壊を避けるため、`sync_once`のFirestoreへの書き込みは`merge=True`(フィールド単位マージ)を用いる。これにより、Cloud Run側の定期的なバックアップPushが、ワーカーが書き込んだ上記フィールドを意図せず上書き・消去することを防ぐ。
  - `elyza_status`(既存カラム)は本例外とは無関係の別概念(golden feedのキュレーションフラグ、後述参照)であるため、意図的に別カラム`elyza_job_status`を新設して衝突を避けている。
- **【instructions/264: データ同期境界の例外化(絶対ルール)】** なぞかけ「評価データ」本体（`NazokakeItem`のGemini/主系フィールド）については、引き続きクラウド側からの新規書き込みを一切禁止しSQLite一元管理を維持する。一方、`apps/evaluator/backend/api/routers/{feedback.py, metrics.py, board.py}`が扱う「フィードバック・テレメトリ・掲示板」等の周辺機能ドメイン（`app_feedbacks`/`telemetry_logs`/`board_posts`/`board_quotas`コレクション）に限り、Cloud RunからFirestoreへの直接書き込みを正式に許可するハイブリッド構成とする(instructions/262の監査で発覚した既存の実装を、意図的な設計として追認・明文化するもの)。この例外は上記コレクションに厳格に限定され、なぞかけ評価データのコレクション(`nazokake_items`)には一切適用されない。
- **非同期バックアップ同期:** ローカルDBに変更が加わった際、非同期ジョブ（`workers/`）を利用してFirestoreへデータをPush（上書き）する。
- **同期失敗時のフェイルセーフ:** 通信エラー等でFirestoreへの同期が失敗した場合は、ローカルの「デッドレターキュー（DLQ）」への退避、または当該レコードへの「未同期フラグ（`sync_status = "pending"`）」の記録によって失敗を可視化する。
- **リトライ機構 (冪等同期):** ネットワーク復旧時、ワーカーが `sync_status = "pending"` の未同期データを拾い上げ、Firestoreに対して冪等（何度実行しても結果が同じ）な上書き操作で同期を再試行する。
- **再帰的赤ペン先生フロー:** 人間（または上位AI）が添削したデータを `corrected_output` に記録し、再度 `evaluator.py` に通して `corrected_scores` を保存する。
- **ステータス管理 (実態: 複数軸の独立フラグ):** 単一のMECEな6状態遷移ではなく、`NazokakeItem` が持つ複数の独立したステータス軸で管理する。
  - `status`: feed.js連携用の全体ステータス（例: `"all_completed"`）。
  - `eval_status`: 評価パイプラインの完了状態（例: `"completed"`）。
  - `llmjp_status`: ELYZA（おまけ）生成パイプラインの完了状態（例: `"pending"` / `"generated"` / `"completed"` / `"failed"`）。実装上のフィールド名は`elyza_status`ではなく`llmjp_status`である点に注意(下記訂正)。
  - `gemini_status` / `elyza_status`: 各生成エンジン別の golden feed 選定フラグ（例: `"golden"` / `"n/a"`）。上記`llmjp_status`とは異なる目的のフィールドであり、混同しないこと(instructions/250でこのドリフトが判明し、オンデマンドELYZAジョブキューには意図的に別カラム`elyza_job_status`を新設した)。
  - `is_user_edited` / `is_golden_data` / `is_approved`: 赤ペン添削・学習データ選定用の真偽値フラグ群。
 これらに加え、トレンド抽出等のバッチキューの排他制御は、ローカルDBのレコードレベルロック（またはトランザクションによるステータス更新）を用いて pending → processing → completed の3状態をアトミックに制御し、複数ワーカーの競合を物理的に排除する。

### 8.3. Infrastructure Layer (LLM Integration) Requirements
外部LLMとの通信とモデルの配役を司る通信基盤。APIコストの削減とローカル環境（VRAM 12GB + RAM 64GB）の最大限の活用を両立するため、「3層防弾アーキテクチャ」を採用する。
【instructions/264: `llm/`はトップレベルディレクトリとして実在しない。実体パスは3節参照。】

- **① ローカルLLM (Ollama) - タイムシェアリング稼働:**
  VRAMの枯渇を防ぐため、モデルは同時に常駐させず、OllamaのKeep-Alive制御等を用いて「逐次ロード/アンロード」によるタイムシェアリングで駆動させる。
  - **`ELYZA` (生成エンジン):** なぞかけの「初回生成」を担当し、強化学習（DPO等）の直接のターゲットとなる。
  - **`Gemma 12b` (現場監督・ハブ):** エラーログ解析とルーティングを担当。問題の難易度を切り分け、次のアクションを決定する。
  - **`Qwen Coder` (ローカルコード修復職人):** Gemmaの指示を受け、AST解析を通過する正確なコード書き換えをローカルで完結させる。
- **② クラウドAPI (Claude) - 最終エスカレーション:**
  - **`Claude Sonnet` (CTO / 最上位Critic):** Qwenが数回リトライしても解決できない複雑なバグや、アーキテクチャレベルの改修のみを担当し、APIコストを最適化する。
- **構造化とリトライ:** Pydantic (`packages/shared_core/nazokake_core/schemas.py` の `NazokakeGenerationOutput`/`Scores`/`Result`/`EvaluationOutput` 等) によるJSON出力を強制する。バリデーションエラー時は最大3回自動リトライし、失敗した場合はエラーとしてDLQへ退避する。
- **【絶対制約】:** エージェントによる `packages/shared_core/nazokake_core/schemas.py` のデータモデル改変、および各モデルの配役境界の自律的な変更を一切禁止する。

### 8.4. Agent Security & Tooling Layer (`tools/`) Requirements
本レイヤーは、Nazo-Agentがローカル環境を操作するための「手」であり、同時にシステムを破壊させないための「防弾ガラス（Sandbox）」として機能する。
- **ファイル構成と機能定義:**
nazo_agent.py / agent_graph.py: Gemma -> Qwen -> Claude という3層防弾エスカレーションパイプラインの実行コア。LLMからのTool Calling要求を受け取り、以下のセキュアツールへルーティングする。

file_reader.py (読み取り専用I/O): エージェントによるファイル読み込みをカプセル化し、encoding="utf-8-sig" 等を用いた安全なテキスト抽出を提供する。

ast_modifier.py（構文防弾化とセキュア書き込み）: エージェントが提案したコード差分（Diff）をASTとしてパースし、セマンティクスが破壊されていないかを検証する。検証通過後、アトミック書き込み（一時ファイル生成・shutil.copystatによるパーミッション/メタデータ保持・os.replace）を用いてディスクへ安全に上書き保存する単一のゲートキーパー。対象ファイル自体が構文エラーでlibcstによりパースできない場合はFail-Closed（即座にエラーとして処理を中断）とし、文字列ベースの推測的フォールバックは行わない。

ast_mapper.py（読み取り専用のシンボル定義抽出）: エージェントがコードを修正する前に、関数名/クラス名からその定義元のソースコード全文をASTで正確に取得するための読み取り専用ツール（get_symbol_definition）。ファイルへの書き込みは一切行わず、修正前のコンテキスト把握を「推測」ではなく実際のASTファクトに基づいて行わせるためのゲートキーパー。

pyright_tool.py (静的型検査): 変更適用前にPyrightをドライランし、型推論エラーが発生するコードのコミットをブロックする。
- **【絶対制約】エージェントのサンドボックス保護:**
  - エージェントがいかに高度な推論を行おうとも、自分自身を律しているこの `tools/` ディレクトリ内のセキュリティロジック（ASTバリデーションの解除や、型チェックのバイパスなど）を自律的に書き換えることは完全にブロックされる。
- **【instructions/264: ツール保護境界(絶対ルール、実装待ち)】** instructions/262の監査で、上記制約がプロンプト規約のみに依存し、コード・インフラいずれのレベルでも実効的な担保(自己防御denylist、read-onlyマウント等)が存在しないことが判明した。今後の実装方針として、インフラ層(`infra/docker-compose.yml`)にて`agent-workspace`の`tools/`マウントをRead-Only(`:ro`)化し、エージェントによる`tools/`自身への書き込みを構造的に不可能にする。ツールが生成する一時ファイル・キャッシュは`tools/`配下ではなく揮発性ディレクトリ(`run/`または`/tmp`)へ出力するようステートを厳密に分離し、`:ro`化によって正規のログ/キャッシュ書き込みまで巻き添えでブロックされないようにする。※本項目は方針の明文化であり、`docker-compose.yml`自体の変更は本タスク(instructions/264、ドキュメントのみ)の対象外。
- **【instructions/264: 型保証境界(絶対ルール、実装待ち)】** instructions/262の監査で、`tools/pyright_tool.py`が実際には`tools/agent_graph.py`のコミットフローにも`.pre-commit-config.yaml`にも組み込まれておらず、LLMが任意に呼び出せるだけのアドバイザリーツールに留まっていることが判明した。今後は(1)自己修復フロー(`agent_graph.py`)内でPyrightをJSON出力モードで組み込み、Qwenによる自律的なエラー解決の入力として使う「エージェント内フィードバックループ」と、(2)最終的な品質担保としてCI/CDパイプライン上で型エラーを機械的にブロックする「ゲートキーパー」の、両輪からなるハイブリッド構成へ移行する。※本項目は方針の明文化であり、`agent_graph.py`/CI設定自体の変更は本タスク(instructions/264、ドキュメントのみ)の対象外。

### 8.5. Local Port Assignments (ローカル開発ポートの決定論的割り当て)
【instructions/260→261: ポート管理のSSoT化】以前は`run_api.ps1`・`tools/nazo_agent.py`・
フロントエンドの複数JSファイルにポート番号が個別にハードコードされ、出自不明な別ポート
との区別がつかない構成ドリフトの温床となっていた(instructions/260の調査で、正規の
起動経路のどれとも一致しない`uv run uvicorn`残骸プロセスがポート8095を占有している
ことが発覚)。正規の割り当ては以下の通りで、単一の正データは`tools/config.py`の
`ToolsSettings`。
- **`7800`:** ローカル開発用API(`run_api.ps1`が起動する`uvicorn main:app`)。SSoT:
  `tools/config.py::ToolsSettings.api_dev_port`。
- **`7300`:** ローカル開発用フロントエンド静的サーバー(`dev_server.py`)。SSoT:
  `tools/config.py::ToolsSettings.frontend_dev_port`。
- **`8080`:** Cloud Run本番環境(`PORT`環境変数、`apps/evaluator/Dockerfile`)。
- **上記以外のポートで待ち受けるローカルの`uvicorn`/バックエンドプロセスは、正規の
  起動経路を持たないゾンビとみなす。** `tools/manage_local_processes.ps1`が、SSoTの
  `api_dev_port`と一致しないポート(既定では8095)を占有する該当プロセスを決定論的に
  検出・終了する。

## 9. Local Cleanroom Infrastructure (`infra/`)
なぞかけ生成および自己修正ループを、常設のローカルDockerインフラ（`infra/docker-compose.yml`）上で安全かつ独立に実行するためのクリーンルーム構成（instructions/001）。

- **物理的な役割分担（ローカル環境 vs クラウド環境）:**
  - **ローカル環境（Agent-Workspace, Gen-Engine, Data-Sync-Daemon）:** 自律コード修正ループの実行（`agent-workspace`）、GPUを占有したvLLMによる大量生成（`gen-engine`）、および正データストアであるローカルSQLiteの実体管理（`data-sync-daemon`）を担う。いずれもホストのGPU/ローカルストレージに物理的に紐づく処理であり、クラウド環境へは移管しない。
  - **クラウド環境（Cloud Run, Firestore）:** 本番トラフィックの受け付け（Cloud Run）と、ローカルSQLiteの「読み取り専用レプリカ/バックアップ」（Firestore、8.2節）としてのみ機能する。クラウド側は自らデータを生成・改変する主体ではない。
- **データフライホイールの非対称性:**
  - **コード（一方向・プル型）:** ローカルで自律修正・検証されたコードは、クラウド（Cloud Run）側からのプル型デプロイによってのみ反映される。クラウドからローカルへコードが逆流することはない。
  - **データ（双方向・還流型）:** ローカルSQLite → Firestoreへの非同期バックアップ同期（8.2節）に加え、本番環境（Cloud Run）で収集された鎮静化（SNS上の不毛な争いをユーモアでアウフヘーベンさせるという本システムの目標、1節参照）の成否データが、Firestore経由でローカル環境へ還流する。
- **ビジネスロジックのフロー（本番成否データ→自己改善トリガー）:** 本番で収集された鎮静化の成否データは、`data-sync-daemon` によってFirestoreからローカルSQLiteへ取り込まれ、ローカルエージェント（`agent-workspace`）の継続的な自己改善（プロンプト評価・DPO/SFTデータ蓄積、7節課題P）を駆動するトリガーとなる。この一連の流れにより、本番運用の実績が次のローカル生成・評価サイクルの質を高める閉路を構成する。
- **ネットワーク境界:** `agent-workspace` と `gen-engine` は外部到達不能な内部網（`cleanroom-internal`）でのみ接続し、`agent-workspace` と `data-sync-daemon` は外部API（Claude/Gemini、Firestore）到達用の`cleanroom-egress`網を個別に持つ。`agent-workspace`のソースマウントは`apps/` `packages/` `tools/` `tests/`に厳格に限定し(加えて`../SSoT_architecture.md:/workspace/SSoT_architecture.md:ro`をRead-Onlyでマウントし、エージェント自身がSSoTを動的に参照できるようにする)、`infra/`自身および`data/`（SSoT実体・鍵情報）は対象外とすることで、自律修正ループがインフラ定義やデータ領域を予期せず破壊することを構造的に防ぐ。
- **【instructions/262→264で更新: data-sync-daemonは完全実装済み】** `data-sync-daemon`は、以前の記述にあった「コンテナ・マウント構成のみのプレースホルダー」状態を脱し、`infra/data-sync-daemon/sync_daemon_entrypoint.py`として完全に実装済みである。具体的には、(1) 固定間隔のポーリングループ(失敗時は指数バックオフ)、(2) Firestoreの`aufheben_events`コレクションからローカルSQLite(`flywheel.db`)への Pull同期、(3) 静的ヒューリスティック(Layer 1)とGeminiによるLLM判定(Layer 2)からなる2層品質サーキットブレーカー、(4) 判定に失敗したイベントを破棄せず退避させる`poisoned_events_dlq`テーブルによるDLQ、まで実装されている。`workers/ondemand_elyza_worker.py`(オンデマンドELYZAジョブキュー、8.2節、人間が手動起動する別物)とは役割・起動契機の異なる、常設バックグラウンドデーモンである点に注意。