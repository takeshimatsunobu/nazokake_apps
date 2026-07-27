## 1. アプリの構成と関係性

本システムは、AIを用いた「なぞかけ」の生成・評価、ユーザーフィードバックの収集、およびシステム自身の自律的なコード修復・MLOpsパイプラインを備えた複合的なアーキテクチャで構成されています。

*   **`apps/evaluator/` (メインアプリケーション)**
    *   **`backend/`**: FastAPIベースのバックエンド。`api/routers/` 配下にAPIエンドポイント（`generate.py`, `feed.py`, `board.py`, `admin.py` 等）を持ち、フロントエンドからのリクエストを処理します。AIモデル（Gemini, ELYZA, Ollama）を呼び出してなぞかけの生成と11軸評価を行います。
    *   **`frontend/`**: ユーザー向けおよび管理者向けの静的HTMLページ群（`index.html`, `admin.html`, `research.html` 等）を提供します。
    *   **`services/`**: AI生成（`generation.py`）、評価（`evaluation.py`）、フィードバック分析（`feedback_analyzer.py`）などのコアドメインロジックを担います。
*   **`apps/batch_factory/` (バッチ処理・データ工場)**
    *   RSSからのトレンド（お題）取得（`rss_publisher.py`, `trends.py`）、LLMを用いた大量のなぞかけ生成・評価（`main.py`, `llm_client.py`）、およびDPO/SFT学習用データの抽出・学習準備（`train_dpo.py`, `manual_dpo_importer.py`）を行うオフラインバッチ群です。
*   **`apps/tactical_cic/` (Tactical CIC)**
    *   標的捕捉、弾頭鋳造（マルチエージェント幕僚会議）、動機監査（コミッサールAI）などのフェーズを持つMDMPエンジン（`mdmp_engine.py`）と、それらを実行するWebhook API（`webhook_api.py`）で構成されるサブシステムです。
*   **`packages/shared_core/` (共有コアパッケージ)**
    *   **`nazokake_core/`**: システム全体で共有されるデータモデルとインフラ層。SQLiteの非同期ORM操作（`database.py`）、Firestoreとの同期（`firestore_sync.py`）、コスト計算（`cost_calculator.py`）、品質のサイレント・デグレードを防ぐサーキットブレーカー（`quality_circuit_breaker.py`）を提供します。AlembicによるDBマイグレーションもここで管理されます。
*   **`tools/` (自律修復・MLOps・運用ツール)**
    *   **Nazo-Agent (`nazo_agent.py`, `agent_graph.py`)**: エラーログからLLM（Qwen, Claude, Gemma）が原因を診断し、AST（抽象構文木）操作（`ast_modifier.py`）を用いてコードを自律的に修正するエージェントシステム。
    *   **ベンチマーク (`benchmark/run_benchmark.py`)**: 修正されたコードをDockerサンドボックス内で安全にテスト・評価するハーネス。
    *   **MLOpsパイプライン (`mlops_pipeline_*.py`, `mlops_trigger.py`)**: モデルの評価や学習データの抽出を自動化し、実験結果をDBに記録します。
    *   **デプロイ管理 (`deploy_poll_daemon.py`)**: Firestoreのステータスをポーリングし、GitOpsベースのPull型デプロイを非同期に実行します。

## 2. ページ動作とUX

フロントエンド（`frontend_pages`）は、バックエンドのAPIエンドポイントと連携して以下のユーザー体験を提供します。

*   **メインページ (`index.html`)**
    *   ユーザーが「お題」を送信すると、バックエンド（`/api/generate`）がGeminiとELYZAの2つのAIモデルを並列で実行します（`progressive_generate`）。各モデルは互いをブロックすることなく「生成 → 本文先行表示 → 評価 → 完了」と段階的に結果を開示し、ユーザーの待機時間を最小化します。
    *   生成されたなぞかけに対して、ユーザーはフィードバック（`/api/nazokake/{doc_id}/feedback`）や人間による投稿（`/api/submit_human`）を行うことができます。
*   **道場破り・殿堂入りフィード (`index.html` 内の機能)**
    *   `/api/feed/items` や `/api/feed/golden` を通じて、他のユーザーやAIが生成したなぞかけ（ランダムシークや殿堂入りデータ）を閲覧・評価できます。
*   **掲示板 (`board.html` 相当)**
    *   `/api/board/items` と `/api/board/post` を通じて、なぞかけに関するスレッドの閲覧や返信の投稿が行われます。
*   **なぞかけ研究所 (`research.html`, `research_data/tab-*.html`)**
    *   `/api/research/articles` から研究記事を取得し、カテゴリ別（basic, comparative, culture, definition, evaluation, generation）のタブUIで体系的に閲覧できます。
*   **管理者ダッシュボード (`admin.html`, `costs_dashboard.html`, `cic_dashboard.html`)**
    *   システムの稼働状況、コスト、デッドレターキュー（DLQ）、Tactical CICのミッション状況などを可視化し、管理者の操作を受け付けます。

## 3. 管理者コンソール（権限と操作）

`/api/admin` 配下のエンドポイントを通じて、管理者は以下の確認・決定・修正を行い、システムに変化を与えます。

*   **データキュレーションと学習データの決定 (`/api/admin/action`)**
    *   対象のなぞかけに対して `gemini_status` や `elyza_status` を `golden`, `approved`, `rejected` に更新します。この操作により、後続のMLOpsパイプライン（DPO/SFTデータ抽出）において、高品質な学習データ（Tier A/B）として採用されるかどうかが決定されます。
*   **デッドレターキュー (DLQ) の管理 (`/api/admin/dlq`, `/api/admin/dlq/action`)**
    *   同期の致命的エラー（ポイズンピル）により隔離されたデータ（`fatal` ステータス）を確認します。管理者はこれらに対して「再試行（pendingへ戻す）」または「破棄（discardedへ変更）」のアクションを適用し、システムを復旧させます。この操作は必ず監査証跡（Audit Trail）として記録されます。
*   **コストと予算の監視 (`/api/admin/costs`)**
    *   APIトークン消費やローカルサーバーの稼働時間に基づくシステムコスト（日本円換算）を確認し、予算超過（ソフトリミット）を監視します。
*   **Few-shotプールの動的更新 (`/api/admin/feedbacks/refresh-fewshot`)**
    *   ユーザーから高評価を得たフィードバックデータを、稼働中のAPIサーバーのメモリ上にあるFew-shotプール（なぞかけ生成時の高品質な例文）へ優先的にマージさせ、AIの生成品質を動的に向上させます。
*   **安全なPull型デプロイの要求 (`/api/admin/deploy`)**
    *   検証サーバーへのデプロイを要求します。このエンドポイントは直接スクリプトを実行せず、Firestoreの `deploy_state` を `pending` に更新するのみです。ローカル常駐のデーモンがこれを検知して安全にデプロイを引き受けるため、ブラウザからの直接的なプロセス起動を防ぐセキュアな構造になっています。

## 4. データフロー

システム内のデータ（ユーザー入力、AI生成物、システムログ）は、以下のフローで循環・永続化されます。

1.  **データの発生と受付 (フロントエンド → バックエンド / ワーカー)**
    *   ユーザーがお題やフィードバックをフロントエンドから送信すると、FastAPIバックエンドが受け取ります。
    *   並行して、バッチワーカー（`rss_publisher.py`）がRSSからトレンドワードを抽出し、「未処理」キューとしてローカルDBに書き込みます。
2.  **AIによる生成と評価 (バックエンド / バッチ ↔ AIモデル)**
    *   バックエンドまたはバッチ処理が、Gemini APIやローカルのOllama/ELYZAにプロンプト（動的Few-shotプールやペルソナを含む）を送信し、なぞかけ本文と思考プロセス（CoT）を生成させます。
    *   生成されたテキストは、Geminiによる11軸評価（`run_evaluation`）にかけられ、スコアが算出されます。
3.  **ローカルDBへの保存とアトミックな状態管理 (バックエンド → SQLite)**
    *   生成結果、スコア、ユーザーフィードバックは、まずローカルのSQLite（`nazokake_items`, `user_feedbacks` 等）に保存されます。書き込みは `SerializedWriter` のキューを経由し、直列化されて安全に処理されます。
4.  **クラウドへの同期とバックアップ (SQLite ↔ Firestore)**
    *   同期デーモン（`firestore_sync.py`, `sync_daemon_entrypoint.py`）がローカルDBの未同期レコード（`pending`）をポーリングし、Firestoreへ非同期でPush同期します。これにより、データがクラウド上に永続化・共有されます。
5.  **MLOpsと自律改善ループ (DB → ワーカー → AIモデル/コードベース)**
    *   **データ抽出**: `extract_dataset.py` 等がDBから高評価データや管理者キュレーションデータを抽出し、重複排除（MinHash/LSH）を経てSFT/DPO用の学習データ（JSONL）を生成します。
    *   **品質監視**: `quality_circuit_breaker.py` が評価スコアの極端な偏りやエラーの連続をスライディングウィンドウで監視し、サイレント・デグレードを検知します。
    *   **自律修復**: エラーが発生した場合、Nazo-Agent（`agent_graph.py`）がエラーログとASTを解析して修正案を生成し、Dockerサンドボックスでのテストを経て、PRドラフトとしてコードベースにフィードバックします。