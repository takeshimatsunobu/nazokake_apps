## 1. アプリの構成と関係性

- **apps/**:
  - `evaluator`: FastAPIベースのバックエンドAPI(`backend/api/routers/`)とフロントエンドUI(`frontend/`)を提供。なぞかけの生成・評価・フィードバック収集を行う。
  - `batch_factory`: LLM(Gemini, Ollama, LocalUnsloth)を用いたなぞかけの生成・評価・DB書き込みを行うバッチ処理群(`main.py`, `import_csv.py`, `firestore_sync_worker.py`など)。
  - `tactical_cic`: 標的捕捉、弾頭鋳造、監査などの機能を提供するWebhook API(`webhook_api.py`)とエンジン(`mdmp_engine.py`)。
- **tools/**:
  - MLOpsパイプライン(`mlops_pipeline_agent.py`, `mlops_pipeline_nazo.py`)、自律エージェント(`nazo_agent.py`, `agent_graph.py`)、デプロイ監視(`deploy_poll_daemon.py`)、データ抽出・学習スクリプト群を配置。
- **packages/**:
  - `shared_core`: アプリ全体で共有する基盤パッケージ。DB接続・ORM定義(`nazokake_core.database`)、Firestore同期(`firestore_sync.py`)、コスト計算(`cost_calculator.py`)、品質サーキットブレーカー(`quality_circuit_breaker.py`)、Alembicによるマイグレーションを提供する。
- **infra/**:
  - データ同期デーモン(`data-sync-daemon/sync_daemon_entrypoint.py`)や検証環境の自動シャットダウン(`verification_env/auto_shutdown.py`)など、インフラストラクチャの運用・監視を担う。

## 2. ページ動作とUX

### apps/evaluator/frontend/public/index.html
- **なぞかけ生成**: ユーザーのアクション → `POST /api/generate` → `generate_ai` → `progressive_generate` (GeminiとELYZAの並列実行) → SQLiteの `nazokake_items` テーブルへUpsert。
- **ステータス確認**: ユーザーのアクション → `GET /api/status/{doc_id}` → `get_status`。
- **フィード取得**: ユーザーのアクション → `GET /api/feed/items` → `get_user_feed`、または `GET /api/feed/golden` → `get_golden_feed`。
- **ユーザー評価**: ユーザーのアクション → `POST /api/feed/evaluate/{doc_id}` → `evaluate_user_item`。
- **人間投稿**: ユーザーのアクション → `POST /api/submit_human` → `submit_human`。
- **フィードバック**: ユーザーのアクション → `POST /api/feedback` → `submit_feedback`、または `POST /api/nazokake/{doc_id}/feedback` → `submit_user_feedback`。
- **掲示板取得**: ユーザーのアクション → `GET /api/board/items` → `get_board_items`。
- **掲示板投稿**: ユーザーのアクション → `POST /api/board/post` → `create_board_post`。

### apps/evaluator/frontend/public/research.html (および tab-*.html)
- **記事一覧取得**: ユーザーのアクション → `GET /api/research/articles` → `list_research_articles`。
- **記事詳細取得**: ユーザーのアクション → `GET /api/research/articles/{article_id}` → `get_research_article`。

### apps/evaluator/backend/templates/costs_dashboard.html
- **コストダッシュボード表示**: ユーザーのアクション → `GET /api/admin/costs/dashboard` → `get_costs_dashboard`。

### public/cic_dashboard.html
- **ヘルスチェック**: ユーザーのアクション → `GET /api/cic/health` → `health_check`。
- **標的捕捉**: ユーザーのアクション → `POST /api/cic/webhook/share` → `receive_share`。
- **監査**: ユーザーのアクション → `POST /api/cic/missions/{mission_id}/audit` → `audit_mission`。
- **射出**: ユーザーのアクション → `POST /api/cic/missions/{mission_id}/fire` → `fire_mission`。
- **BDA取得**: ユーザーのアクション → `GET /api/cic/missions/{mission_id}/bda` → `get_bda`。

### apps/evaluator/frontend/public/admin.html
- (セクション3で詳述)

### apps/evaluator/frontend/public/404.html
- 存在しないページへのアクセス時に表示。

## 3. 管理者コンソール（権限と操作）

### キュレーション操作
- **API**: `POST /api/admin/action`
- **バックエンド関数**: `apply_human_action`
- **DB変更**: 対象なぞかけの `gemini_status` / `elyza_status` を更新 (golden/approved/rejected)。

### DLQ（デッドレターキュー）管理
- **API**: `GET /api/admin/dlq`
- **バックエンド関数**: `get_dlq_items`
- **確認内容**: DLQ(隔離済み)アイテムの一覧、隔離理由(`last_sync_error`)、`retry_count` を取得。
- **API**: `POST /api/admin/dlq/action`
- **バックエンド関数**: `apply_dlq_action`
- **DB変更**: DLQアイテムへ「再試行」または「破棄」を適用。操作成功時、既存データを破壊しない追記専用の監査証跡(`audit_logs`テーブル)を記録。

### 監査証跡の確認
- **API**: `GET /api/admin/audit_logs`
- **バックエンド関数**: `get_audit_logs`
- **確認内容**: 監査証跡(`audit_logs`)を作成日時の降順で最大100件取得。

### デプロイ要求
- **API**: `POST /api/admin/deploy`
- **バックエンド関数**: `trigger_deploy`
- **DB変更**: Firestoreの `system_configs/deploy_state` ドキュメントへ `{"status": "pending", ...}` を書き込む。実際のデプロイはローカル常駐の `deploy_poll_daemon.py` がポーリングして非同期に実行。

### コスト管理
- **API**: `GET /api/admin/costs`
- **バックエンド関数**: `get_costs`
- **確認内容**: コストログの取得。

### フィードバック管理とFew-shotプール更新
- **API**: `GET /api/admin/feedbacks`
- **バックエンド関数**: `get_admin_feedbacks`
- **確認内容**: 管理者向けフィードバック一覧の取得。
- **API**: `POST /api/admin/feedbacks/refresh-fewshot`
- **バックエンド関数**: `refresh_fewshot_pool`
- **DB変更**: 稼働中のAPIサーバー自身のプロセス内でFew-shotプールと評価プロンプトの動的補正を更新。

## 4. データフロー

1. **UIからの入力**: ユーザーや管理者がフロントエンド(UI)からアクションを起こすと、FastAPIのルーター(`api_routes`)を経由してバックエンド関数が呼び出される。
2. **バックエンド処理とAI生成**: バックエンド関数(`generate_ai`, `progressive_generate`等)は、GeminiやELYZAなどのLLMを呼び出し、なぞかけの生成や評価を行う。
3. **ローカルDBへの保存**: 生成結果やユーザーのフィードバック、管理者のアクションは、`nazokake_core.database` を通じてローカルのSQLite(`nazokake_items`, `audit_logs`, `TriggerStateORM`等)に保存される。
4. **ワーカーによる同期**: `firestore_sync.py` の `sync_once` 関数が、SQLiteの未同期データ(pending/error)をFirestoreへPushする。また、起動時には `async_restore_from_firestore` がFirestoreからSQLiteへデータをPullする。
5. **MLOpsとバッチ処理**: `tools/` 配下のMLOpsパイプラインや `apps/batch_factory/` のバッチ処理が、DBからデータを抽出し、学習データセットの作成やモデルの評価を行い、結果を実験管理DB(`mlops_experiments.db`)や静的JSONに記録する。