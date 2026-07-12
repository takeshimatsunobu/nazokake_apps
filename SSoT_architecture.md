# Nazo-kake System: Project Context & SSoT

## 1. System Overview & Mission
- **Project Goal:** なぞかけ自動評価・生成システムの構築、および「Nazo-Agent」による自律開発支援パイプラインの確立。
- **Ultimate Vision:** 最新の技術要件とシステムの実行エラーを日次で自律監査し、コードの修正・テスト・デプロイまでを人間の介入なしに完遂する完全自律型パイプラインの実現。
- **Current Phase:** 完全自律化に向けた「厳密監視フェーズ（初期3ヶ月）」。AIによるテスト陳腐化判定と自動PR作成（Human-in-the-Loop）を組み込み、監視と評価の基盤を構築・検証中。

## 2. System Architecture & Subsystems
- **Deployment Topology (Local-First):** FastAPI（バックエンド）、フロントエンド、バッチ工場（`apps/batch_factory`）のすべてをローカルPC上で稼働させることを基本方針とする。外部（スマホ等）からのアクセスが必要な場合に限り、Cloudflare Tunnel経由でローカルのフロントエンド/APIを外部公開するハイブリッド構成を取り、常時稼働のクラウドサーバーには依存しない。
- **Y-Shaped Data Pipeline Architecture:**
  - **自律・実験的フロー:** `workers/` モジュールがバックグラウンドで自律的にお題を抽出し、実験的な生成・評価・データ蓄積を非同期で行う。
  - **ユーザー駆動フロー:** `interfaces/` モジュールがユーザーからの同期的なリクエスト（オンデマンド生成・評価）を受け付ける。
  - **共通収束:** 双方の入り口から入ったデータは、共通の生成・評価パイプラインを通過し、単一の「ローカルSSoT DB」へと収束する（クラウド側のFirestoreへは非同期の一方向バックアップ同期のみが行われる。詳細は8.2節）。
- **Nazo-Agent Autonomous Pipeline:**
  - Pytestの実行結果を起点とする決定論的エスカレーション機構（Pytest -> Gemma -> Qwen -> Claude）。
  - 客観的ファクト抽出と、テストコード保護を内包する自己修復・評価ループ。

## 3. Directory Structure & Strict Boundaries
本システムでは、自律エージェントが安全にコードを修正できるよう、インフラストラクチャとドメインロジックの境界を厳格に分離する。

- **`llm/` (Infrastructure: LLM Integration & Schemas)**
  - **責務:** 外部LLM（Ollama, Claude）との通信基盤、およびPydanticを用いた入出力の構造化（スキーマ定義）。
  - **制約（Agent Sandbox）:** プロンプト等、ドメイン固有のテキストをここにハードコードしない。Criticによる自律的な修正の対象外（原則禁止）とする。
- **`evaluation/` (Domain: Evaluation Pipeline & Prompts)**
  - **責務:** なぞかけの品質評価、スコアリングのルール定義、客観的ファクト抽出。
  - **制約（Agent Sandbox）:** Criticはコンテンツ内容や評価基準自体には干渉しない。
- **`workers/` (Infrastructure: Autonomous Batch Workers)**
  - **責務:** 非同期バッチ処理の実行、実験的量産タスクの管理、排他制御、デッドレター処理（DLQ）。
- **`interfaces/` (Infrastructure: User Interfaces & APIs)**
  - **責務:** リアルタイムなユーザー入力の受付、エンドユーザー駆動のエンドポイントおよび同期制御の提供。
- **`tools/` (Infrastructure & Security: Agent Local Tools)**
  - **責務:** エージェントがローカル環境を操作するための防弾化されたセキュアI/Oの提供、AST解析、静的型チェック。

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
[Priority High] 課題 I (🚨 現在進行中): tools/ 内におけるアトミック書き込みの完全化（shutil.copymode によるメタデータ保持と排他制御）。

[Priority Medium] 課題 L: OpenTelemetry等を活用したLLMOps専用トレース基盤（LangSmith, Datadog等）へのログ統合。

[Priority Medium] 課題 P: DPO/SFT 完全自動パイプラインの構築（データ抽出からモデル評価まで）。

## 8. Detailed Module Specifications (モジュール詳細仕様)

### 8.1. Domain Layer (`evaluation/`) Requirements
- **概要:** なぞかけの「評価ロジック」と「プロンプト」をカプセル化する純粋なドメイン層。状態を持たない（Stateless）。
- **`evaluation/evaluator.py`:** LLMを呼び出しスコアリングを実行する。DBへの保存は行わない。赤ペン先生による修正データに対しても、全く同一のロジックで再評価を行う。
- **`evaluation/prompts.py`:** 評価基準をLLMに指示するためのテキストテンプレート。
- **【絶対制約】:** エージェントの役割はシステムエラーの修復（SRE/QAの責務）に限定される。なぞかけのコンテンツ内容や `evaluation/prompts.py` のテキストを自律的に書き換えることは厳格に禁止する。

### 8.2. Infrastructure Layer (`workers/`, `interfaces/`, & Database) Requirements
- **モジュール分離:**
  - **`workers/`:** 実験的・量産型の非同期ワーカー。辞書やトレンドからお題を抽出し、MLデータの継続的な拡充を担当。
  - **`interfaces/`:** ユーザー指定のお題でのリアルタイム生成、または評価リクエストを同期的に処理するエンドポイント。
- **Local SSoTモデル (絶対的正データストア):** ローカルDB（SQLite等）を単一の絶対的な正（Single Source of Truth）と定義する。すべての新規データ生成・更新は必ずローカルDBに対してのみ行う。ドキュメント契約は `packages/shared_core/nazokake_core/schemas.py` の `NazokakeItem` としてPydanticで凍結し、`doc_id`/`odai`/`nazokake_text`/`scores`/`s_total`等の必須フィールドを保証する。
- **Firestoreの役割 (読み取り専用レプリカ/バックアップ):** Firestoreはクラウド上の「読み取り専用レプリカ」および「バックアップ」としてのみ機能させる。クラウド側からの新規書き込みは一切禁止し、ローカルDB→Firestoreへの一方向同期のみを許可することで、スプリットブレイン問題を物理的に排除する。
- **非同期バックアップ同期:** ローカルDBに変更が加わった際、非同期ジョブ（`workers/`）を利用してFirestoreへデータをPush（上書き）する。
- **同期失敗時のフェイルセーフ:** 通信エラー等でFirestoreへの同期が失敗した場合は、ローカルの「デッドレターキュー（DLQ）」への退避、または当該レコードへの「未同期フラグ（`sync_status = "pending"`）」の記録によって失敗を可視化する。
- **リトライ機構 (冪等同期):** ネットワーク復旧時、ワーカーが `sync_status = "pending"` の未同期データを拾い上げ、Firestoreに対して冪等（何度実行しても結果が同じ）な上書き操作で同期を再試行する。
- **再帰的赤ペン先生フロー:** 人間（または上位AI）が添削したデータを `corrected_output` に記録し、再度 `evaluator.py` に通して `corrected_scores` を保存する。
- **ステータス管理 (実態: 複数軸の独立フラグ):** 単一のMECEな6状態遷移ではなく、`NazokakeItem` が持つ複数の独立したステータス軸で管理する。
  - `status`: feed.js連携用の全体ステータス（例: `"all_completed"`）。
  - `eval_status`: 評価パイプラインの完了状態（例: `"completed"`）。
  - `gemini_status` / `elyza_status`: 各生成エンジン（Gemini / ELYZA）別の生成完了状態（例: `"pending"` / `"n/a"`）。
  - `is_user_edited` / `is_golden_data` / `is_approved`: 赤ペン添削・学習データ選定用の真偽値フラグ群。
 これらに加え、トレンド抽出等のバッチキューの排他制御は、ローカルDBのレコードレベルロック（またはトランザクションによるステータス更新）を用いて pending → processing → completed の3状態をアトミックに制御し、複数ワーカーの競合を物理的に排除する。

### 8.3. Infrastructure Layer (`llm/`) Requirements
外部LLMとの通信とモデルの配役を司る通信基盤。APIコストの削減とローカル環境（VRAM 12GB + RAM 64GB）の最大限の活用を両立するため、「3層防弾アーキテクチャ」を採用する。

- **① ローカルLLM (Ollama) - タイムシェアリング稼働:**
  VRAMの枯渇を防ぐため、モデルは同時に常駐させず、OllamaのKeep-Alive制御等を用いて「逐次ロード/アンロード」によるタイムシェアリングで駆動させる。
  - **`ELYZA` (生成エンジン):** なぞかけの「初回生成」を担当し、強化学習（DPO等）の直接のターゲットとなる。
  - **`Gemma 12b` (現場監督・ハブ):** エラーログ解析とルーティングを担当。問題の難易度を切り分け、次のアクションを決定する。
  - **`Qwen Coder` (ローカルコード修復職人):** Gemmaの指示を受け、AST解析を通過する正確なコード書き換えをローカルで完結させる。
- **② クラウドAPI (Claude) - 最終エスカレーション:**
  - **`Claude Sonnet` (CTO / 最上位Critic):** Qwenが数回リトライしても解決できない複雑なバグや、アーキテクチャレベルの改修のみを担当し、APIコストを最適化する。
- **構造化とリトライ:** Pydantic (`llm/schemas.py`) によるJSON出力を強制する。バリデーションエラー時は最大3回自動リトライし、失敗した場合はエラーとしてDLQへ退避する。
- **【絶対制約】:** エージェントによる `llm/schemas.py` のデータモデル改変、および各モデルの配役境界の自律的な変更を一切禁止する。

### 8.4. Agent Security & Tooling Layer (`tools/`) Requirements
本レイヤーは、Nazo-Agentがローカル環境を操作するための「手」であり、同時にシステムを破壊させないための「防弾ガラス（Sandbox）」として機能する。
- **ファイル構成と機能定義:**
nazo_agent.py / agent_graph.py: Gemma -> Qwen -> Claude という3層防弾エスカレーションパイプラインの実行コア。LLMからのTool Calling要求を受け取り、以下のセキュアツールへルーティングする。

file_reader.py (読み取り専用I/O): エージェントによるファイル読み込みをカプセル化し、encoding="utf-8-sig" 等を用いた安全なテキスト抽出を提供する。

ast_modifier.py / ast_mapper.py (構文防弾化とセキュア書き込み): エージェントが提案したコード差分（Diff）をASTとしてパースし、セマンティクスが破壊されていないかを検証する。検証通過後、アトミック書き込み（一時ファイル生成・shutil.copymodeによるメタデータ保持・os.replace）を用いてディスクへ安全に上書き保存する単一のゲートキーパー。

pyright_tool.py (静的型検査): 変更適用前にPyrightをドライランし、型推論エラーが発生するコードのコミットをブロックする。
- **【絶対制約】エージェントのサンドボックス保護:**
  - エージェントがいかに高度な推論を行おうとも、自分自身を律しているこの `tools/` ディレクトリ内のセキュリティロジック（ASTバリデーションの解除や、型チェックのバイパスなど）を自律的に書き換えることは完全にブロックされる。