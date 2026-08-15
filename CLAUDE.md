# CLAUDE.md — なぞかけ道場プロジェクト 引き継ぎ用ドキュメント

> このファイルは、このリポジトリに直接アクセスできない別のClaudeセッションに状況を
> 引き継ぐ目的で作成された。実際にコードを読んで確認した内容のみを記載しており、
> 未確認の事項には明示的に「未確認」と記す。値を含む秘密情報（APIキー等）は一切含めない。
> 作成日: 2026-08-12。作成時点のHEADコミット: `42a2297`。

## 1. プロジェクトの目的と概要

**「なぞかけ」**（例:「〇〇とかけて△△と解く。その心は…」形式の日本語言葉遊び）を、
AIが自動生成・自動評価するプロジェクト。「和風スチームパンク」（桜×抹茶×鉄色×真鍮色）
という世界観を持つ、ねづっち氏非公認の学術的AIプロジェクトという体裁を取る
（`apps/evaluator/PROJECT_CORE.md`）。

中核にあるのは **ローカルLLM（ELYZA）とクラウドLLM（Gemini）を組み合わせたデュアルAI
パイプライン**で、ユーザーが遊びながらAIを育てる（人間のフィードバックによる強化学習
＝RLHF的な仕組み）プラットフォームを志向している。

モノレポ構成で、性質の異なる3つのアプリケーションが同居している。

| アプリ | 役割 | 状態 |
|---|---|---|
| `apps/evaluator` | 本番Webアプリ（生成・評価・フィード・管理コクピット） | 稼働中・開発が最も活発 |
| `apps/persona_main_function` | 「ペルソナ」（語り手キャラクター）別になぞかけを生成する独立マイクロサービス | 2026-08-11に新規追加されたばかり |
| `apps/batch_factory` | オフラインの大量生成・モデル学習（DPO/SFT）用バッチパイプライン | 独立したgitリポジトリとして同居（後述） |

## 2. 技術スタック

Python系は基本的に **[uv](https://github.com/astral-sh/uv)**（`pyproject.toml` +
`uv.lock`）で依存管理されている。`requirements.txt`が併存する箇所もあるが、
Python 3.11+ の各アプリの一次情報は `pyproject.toml`。

### apps/evaluator/backend
- Python `>=3.11`
- FastAPI `0.140.0` / uvicorn `0.51.0` / pydantic `2.13.4`
- firebase-admin `7.5.0` / google-cloud-firestore `2.28.0`
- google-genai `2.14.0`（Gemini呼び出し）
- httpx `0.28.1` / loguru `0.7.3`（構造化ロギング） / mcp `1.28.1`
- google-cloud-bigquery（GCPコスト集計）、opentelemetry-api
- `nazokake-core`（= `packages/shared_core`、editableなローカルパス依存）

### apps/evaluator/frontend
- Vanilla JS（実行時ライブラリ依存なし、フレームワーク不使用）
- devDependencies: `openapi-typescript ^7.4.0`, `typescript ^5.6.0`
  （バックエンドのOpenAPI契約から型を静的生成し検査する用途）

### apps/persona_main_function
- Python `>=3.11`
- fastapi `0.141.1`（`[standard]`）/ uvicorn `0.52.1`（`[standard]`）
- pydantic `2.13.4` / firebase-admin `7.5.0` / google-genai `2.17.0`
- python-dotenv `1.2.2`
- `nazokake-core`（ローカルパス依存）

### apps/batch_factory
- Python `==3.13.*`（他アプリと異なるバージョン指定）
- pydantic `2.13.4` / firebase-admin `7.4.0` / google-genai `2.8.0`
- chromadb `1.5.9`（few-shot検索用ベクトルDB） / sentence-transformers `5.5.1`
- torch `2.12.0` / transformers `5.12.0` / janome `0.5.0`（形態素解析） / tenacity `9.1.4`
- 学習専用（`requirements-train.txt`）: unsloth（gitHEAD参照）、trl `0.18.2–0.24.0`、
  peft `>=0.18.0`、accelerate、bitsandbytes、datasets。RTX 4060 / CUDA 12.4 / Python 3.11想定
  （`requirements-train.txt`はメインの`pyproject.toml`のPython 3.13指定と別環境の可能性あり、**未確認**）
- `nazokake-core`（ローカルパス依存）

### packages/shared_core（3アプリ共通の共有パッケージ）
- パッケージ名 `nazokake-core`。pydantic>=2, sqlalchemy>=2, aiosqlite, firebase-admin>=6,
  alembic>=1.13, opentelemetry-api/sdk

### インフラ
- 本番: GCP Cloud Run（バックエンド） + Firebase Hosting（フロントエンドSPA）
- DB: SQLite（ローカル/Cloud Run上は`/tmp`）をSSoTとし、Firestoreへ非同期でPush/Pull同期
  （詳細は §5「設計上の決定事項」参照）
- コンテナ: Docker（各アプリに`Dockerfile`）、Cloud Build（`cloudbuild*.yaml`）
- CI/CD: GitHub Actions（`.github/workflows/`、詳細は §4）

## 3. ディレクトリ構成

トップレベル（開発・運用上重要なもののみ抜粋。フルツリーは巨大なため省略）:

```
apps/
  evaluator/       本番Webアプリ（backend: FastAPI, frontend: Vanilla JS SPA）
  persona_main_function/  ペルソナ別なぞかけ生成マイクロサービス（独立Cloud Runデプロイ）
  batch_factory/   オフライン大量生成・DPO/SFT学習パイプライン（★独立gitリポジトリ、下記参照）
  tactical_cic/    未調査。今回の引き継ぎ範囲外（★未確認）
packages/
  shared_core/     3アプリ共通の共有Pythonパッケージ nazokake_core（DB, Firestore同期, few-shot, persona定義等）
workers/
  ondemand_elyza_worker.py   ユーザーのローカルGPU機でFirestoreジョブキューをポーリングし、
                             ELYZA(Ollama)生成をオンデマンド実行するワーカー
tools/             50以上の運用/MLOps/診断スクリプト群（詳細は §3.1）
infra/             Docker Compose定義・GCPセットアップスクリプト・物理ノード構築手順
data/              研究記事データ、学習用データセット、credentials置き場（値は.gitignore対象）
run/               実行時生成物（監査ログ、SSoT監査レポート、タスク状態JSON等）
archive/           過去のアーカイブ（旧アプリのバックアップ、使われなくなったスクリプト群、
                   過去のinstructions履歴。§7参照）
tests/             リポジトリ横断のpytestスイート（e2e, verification_env）
run_api.ps1        evaluatorバックエンドの安全な起動ラッパー（§4参照）
start_dev.ps1      run_api.ps1 と scripts/start_elyza_worker.ps1 を別ウィンドウで一括起動する開発用スクリプト
scripts/start_elyza_worker.ps1  ondemand_elyza_worker.py のクラッシュ時自動再起動ループ付き起動ラッパー
Makefile           extract-data / train-model / mlops-pipeline の3ターゲットのみ
```

### 3.1 apps/evaluator/backend/ の内部構成

```
api/routers/*.py    ドメイン別ルーター（旧 endpoints.py を分割済み。14ファイル）
  admin.py            レビュー・デプロイ操作・監査証跡
  admin_auth.py        招待制認証（招待URL→Googleログイン→オーナー承認）
  admin_config.py      ペルソナ設定の時限/永続上書き
  admin_costs.py        GCPコスト管理（BigQuery Billing Export集計）
  admin_feedbacks.py    管理者向けフィードバック集計
  admin_health.py        稼働ヘルスチェック（DLQ・APIエラー率）
  admin_review.py        「直談判」レビュー（赦す/リセット/却下）・Few-shot採用
  board.py                なぞかけ掲示板（Firestore直接読み書きを許可された唯一の例外ドメイン）
  feed.py                  「道場破り」フィード
  feedback.py               ご意見箱
  generate.py                生成ドメイン（Gemini即時 + ELYZAおまけの非同期並走）
  metrics.py                  テレメトリ記録
  research.py                  なぞかけ研究所（公開記事）
  submission.py                投稿関連
  user_feedback.py              ユーザーフィードバック受付
services/*.py
  generation.py    Gemini(主軸)・ELYZA(おまけ)生成の中核。VRAM排他制御あり
  evaluation.py     11軸評価エンジン
  output_parser.py   LLM出力からのJSON抽出/検証
  email.py            招待メール送信（Gmail SMTP）
  feedback_analyzer.py AI自己評価とユーザー評価の乖離分析
  toku_kokoro.py         「解き/そのこころ」抽出共有ヘルパー
  unlock_review.py        「直談判」への赦す/リセット/却下アクション
models/schemas.py   Pydanticスキーマ定義（全モデルのSSoT）
```

### 3.2 apps/persona_main_function/ の内部構成

```
api/routers/generate.py    POST /v1/generate（Step1推定→Step2生成の中核オーケストレーション）
api/routers/personas.py     GET /v1/personas
api/routers/timeline.py      GET /v1/timeline、座布団リアクション
api/routers/unlock.py         直談判リクエスト受付
api/routers/corrections.py     「赤ペン」ユーザー訂正受付
services/step1_estimation.py  お題単体の属性推定（persona非依存、Firestoreキャッシュあり）
services/step2_generation.py   ペルソナ反映生成。Route A(正常入力)/Route B(無効入力への
                                エンタメ的切り返し)に分岐。Few-shot注入あり
services/penalty.py             段階的ブロック（荒らし対策）
services/cost_logging.py         Gemini呼び出しのコスト/レイテンシ計測
```

### 3.3 packages/shared_core/nazokake_core/ の内部構成

```
database.py        SQLite(SSoT)接続管理。SQLAlchemy 2.0 + aiosqlite。単一の
                    "Serialized Writer"タスクで書き込みを直列化しWALモードで排他制御。
                    ORMテーブル: NazokakeItemORM, AuditLogORM, TriggerStateORM,
                    QualityCircuitBreakerStateORM, ResearchArticleORM
firestore_sync.py   ローカルSQLite→Firestoreへの一方向Push同期、および起動時Pull復元
fewshots.py         レビューで承認された「Golden」few-shot例の共有プール
personas.py         語り手ペルソナ定義のSSoT（evaluator/persona_main_function/batch_factory共通）
parser.py           LLM出力（ELYZA系）からなぞかけ結果を頑健抽出する共通パーサー
cost_calculator.py  トークン使用量→JPYコスト換算
quality_circuit_breaker.py  推論品質のサイレント劣化を検知するスライディングウィンドウ検知器
training_filter.py  学習データのデータポイズニング防止フィルタのSSoT
env_config.py       `.env`をディレクトリを遡って探索・読み込み
exceptions.py       共通ドメイン例外
models.py           ★注意: database.pyとは別に、独立した宣言的ベースでTriggerStateORMが
                    再定義されている（重複/レガシーの疑いあり、未確認、要調査）
```

## 4. 起動・ビルド・テストのコマンド

### 開発環境の起動
```powershell
# バックエンド(FastAPI)とELYZAワーカーを別ウィンドウで一括起動
.\start_dev.ps1
# → 内部で run_api.ps1 と scripts\start_elyza_worker.ps1 を pwsh.exe 別プロセスとして呼ぶ
```

`run_api.ps1`（直接実行も可）が行っていること:
1. **環境ガード**: `.venv`が無ければ即失敗（venv必須）
2. **VRAM保護**: `--workers`は常に1固定。複数ワーカーを渡すとエラーで拒否
   （ELYZA呼び出しのVRAM排他制御が単一プロセス前提のため）
3. `tools/export_openapi.py`でOpenAPIスキーマをダンプし、`npm run generate-types`で
   フロントエンド用`api.d.ts`を再生成（npm未導入なら警告付きスキップ）
4. `tools/run_migrations.py`でAlembicマイグレーションを適用
5. `uvicorn main:app --host 127.0.0.1 --port <port> --workers 1` を
   `apps/evaluator/backend`で実行

本番（Cloud Run, `apps/evaluator/Dockerfile`）: `uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}`

### テスト
```bash
# リポジトリ横断のpytestスイート（CI: .github/workflows/pyright_check.yml が実行）
uv run pytest tests/ -v

# evaluator backend単体のfail-closed検証（pytest形式）
cd apps/evaluator/backend && pytest test_fail_closed.py
```
`apps/evaluator/`直下には他に `test_elyza_diag.py` / `test_local_elyza.py` /
`test_ollama_500.py` 等、ELYZA/Ollama疎通確認用のアドホックな検証スクリプトが複数あるが、
これらはpytest形式ではなく手動`asyncio.run`実行を想定したもの（**未確認**: pytest収集対象に
なっているかは要確認）。

### Lint / 型チェック
```bash
ruff check .          # .pre-commit-config.yaml で v0.15.20固定、--no-fix
uv run python tools/pyright_tool.py --gate "origin/main"   # 変更行のみのラチェット型検査
```

### バッチ/MLOps関連
```bash
make extract-data      # tools/extract_training_data.py
make train-model        # tools/train_local_model.py --dry-run
make mlops-pipeline      # 上記2つを連結
```

## 5. 設計上の決定事項とその理由

- **SQLiteをSSoT、Firestoreはバックアップレプリカ**: `packages/shared_core/nazokake_core/database.py`
  と `firestore_sync.py` により、ローカル/Cloud Run上のSQLiteが正とされ、Firestoreへは
  一方向Push（+起動時Pull復元）する設計。`apps/evaluator/PROJECT_CORE.md`（ドキュメント）は
  「Firestoreのみ、クライアント直接アクセス禁止」と書いているが、これは**実装と乖離した
  古い記述**である可能性が高い（実コードの方が信頼できる、§7参照）。掲示板機能(`board.py`)
  のみFirestore直接読み書きが許可された明示的な例外。
- **VRAM排他制御と`--workers 1`固定**: ローカルGPU(RTX 4060 8GB)でELYZA(Ollama)を安全に
  動かすため、`generation.py`にセマフォ（`_OLLAMA_SEMAPHORE`）を設け、FastAPIプロセス自体も
  ワーカー数1に固定している。複数ワーカーにするとVRAM排他制御が意味を失いOOMを招くため。
- **オンデマンドELYZAワーカーによるローカルGPU連携**: Cloud Run上のFastAPIはローカルGPUへ
  直接アクセスできないため、`workers/ondemand_elyza_worker.py`がユーザーのローカルPC上で
  Firestoreジョブキューをポーリングし、生成結果を書き戻す構成になっている。ジョブが失敗
  すると即座に`dead_letter`化し（2026-08-11時点、旧仕様はリトライキュー方式だったが撤廃）、
  クラウド側は一定時間待ってGemini Flash Liteへの「代打」フォールバックへ切り替える。
- **ELYZA出力へのGemini混入の禁止**: 直近のコミット(`42a2297`)で、ELYZA生成が失敗した際に
  黙ってGeminiの結果へフォールバックする挙動を廃止し、明示的に例外を送出するよう変更された。
  理由は「ELYZAの出力」と称するデータに実際にはGeminiの出力が混入するデータ完全性の問題を
  解消するため（=データ計測の正しさを、ユーザー体験上のフォールバックの快適さより優先）。
- **best-of-3 → best-of-1への変更**: 同じくコミット`42a2297`で、ELYZA生成の並列3本勝負
  （best-of-3、最高得点をDPO選好ペアとして記録）方式を廃止し、1回勝負（best-of-1、
  「一発入魂」）に変更。レイテンシ最適化（ポーリング間隔8.0秒→2.0秒等）が目的。
- **リポジトリ直下の`packages/shared_core`を共有パッケージ化**: evaluator/persona_main_function/
  batch_factoryの3アプリすべてが、DB接続・Firestore同期・persona定義・few-shotプール等の
  共通ロジックを`nazokake-core`パッケージとして`pyproject.toml`のローカルパス依存
  （editable install）で参照する。ロジックの重複を避ける意図。ただしDockerビルド時は
  リポジトリルートをビルドコンテキストにする必要があり(`apps/persona_main_function/Dockerfile`等)、
  このためCloud Buildの構成が単純な「アプリディレクトリ単体ビルド」にできない制約が生じている。
- **PowerShell起動スクリプトの`-EncodedCommand`化**: `start_dev.ps1`は旧版で手組みの
  クォートエスケープ付き`-Command`文字列を使っていたが、ネストが壊れると子プロセスが
  サイレントに落ちる問題があったため、Base64エンコードした`-EncodedCommand`方式へ変更
  （詳細コメントは`start_dev.ps1`冒頭を参照）。
- **なぜ`apps/batch_factory`が独立gitリポジトリなのか**: 未確認（意図的な設計かどうか
  不明）。`.gitmodules`はルートに存在しないため正式なsubmoduleではなく、gitが
  「埋め込みリポジトリ」（gitlink, mode 160000）として扱っている状態（§7で詳述）。

## 6. 命名規則・コーディング規約

- **コミットメッセージ**: Conventional Commits風（`feat(scope): ...`, `fix(scope): ...`,
  `perf(scope): ...`, `chore(scope): ...`）。日本語で「何を・なぜ」を詳細に書く文化がある
  （本文が長め、背景・理由・調査結果まで書き込む傾向）。
- **依存管理**: uv優先（`pyproject.toml` + `uv.lock`）。`requirements.txt`が残っている
  箇所は基本的にレガシーか補助的なもの（例: `apps/batch_factory/requirements.txt`は
  現在破損状態、§7参照）。
- **Lint**: ruff（バージョンは`.pre-commit-config.yaml`と各`.ruff_cache`のバージョンで
  固定、`--no-fix`＝自動修正はせず検出のみ）。
- **型チェック**: Pyright。CIでは「変更行のみ」を検査するラチェット方式
  （`tools/pyright_tool.py --gate`）。導入時点で`tools/`配下だけで既存338件のエラーが
  あったため、全件ブロックではなく差分ブロック方式を採用した経緯がある。
- **環境変数アクセス**: `nazokake_core.env_config`が`.env`をディレクトリツリーを遡って
  自動探索する仕組みがあるため、各アプリで個別に`.env`パスを気にする必要は薄い設計。
- **Firestoreコレクションアクセスの原則**: 基本はSQLite経由（§5参照）。直接Firestore
  アクセスは`board.py`（掲示板）や`workers/ondemand_elyza_worker.py`（特定フィールドの
  ホワイトリストに限定して書き込み）など、明示的な例外としてのみ許可される設計思想。
- **PowerShellスクリプトの文字コード**: `.ps1`はBOM無しUTF-8で保存する慣習。Windows
  PowerShell 5.1(`powershell.exe`)はBOM無しUTF-8を誤読するため、`pwsh.exe`
  (PowerShell 7+)を優先的に使う設計になっている（`start_dev.ps1`参照）。

## 7. 外部API・環境変数・設定ファイル一覧

**注意**: 以下はすべて「変数名と用途」のみ。実際の値は本ドキュメントは元より、
リポジトリのどのファイルにも書かないこと。

### 外部API/サービス
- **Google Gemini API**（`google-genai`経由）: なぞかけ生成の主軸・11軸評価・
  persona_main_functionのStep1/Step2生成すべてで使用
- **Ollama（ローカル）**: ELYZA（`elyza:8b` / LLM-JP系）モデルのローカル推論エンドポイント
  （既定 `http://localhost:11434`）
- **Firebase Admin SDK / Firestore**: 認証・データ同期・掲示板・ジョブキュー
- **Firebase Hosting**: 各アプリのフロントエンド静的ホスティング
- **GCP Cloud Run**: バックエンドの本番実行環境
- **GCP Artifact Registry**: Dockerイメージ格納先
- **GCP BigQuery（Billing Export）**: 管理コクピットのコスト集計機能が参照
- **Gmail SMTP**（smtp.gmail.com:465）: 管理者招待メール送信
- **Hugging Face**: モデル/データセットのダウンロード（batch_factory学習パイプライン）
- **Anthropic API**: `requirements_orchestrator.txt`に`anthropic`パッケージが含まれ、
  CD時にも`ANTHROPIC_API_KEY`がSecretとして注入される（`tools/`配下の自律エージェント
  スクリプト群が使用している可能性が高いが、用途の全容は**未確認**）

### 主な環境変数（キー名のみ・用途）

| 変数名 | 用途 | 使用箇所 |
|---|---|---|
| `GEMINI_API_KEY` | Gemini API認証 | evaluator, persona_main_function, batch_factory 共通 |
| `ANTHROPIC_API_KEY` | Anthropic API認証 | CD/tools系（詳細未確認） |
| `HF_TOKEN` | Hugging Face認証 | batch_factory学習パイプライン |
| `NAZOKAKE_DB_PATH` | SQLite DBファイルの絶対パス（SSoT） | shared_core, evaluator, workers共通 |
| `VRAM_LOCK_PATH` | ELYZA(Ollama)呼び出し排他制御ロックファイルパス | evaluator, workers |
| `LLMJP_MODEL` | ELYZA/LLM-JPモデル名（既定 `elyza:8b`） | evaluator |
| `EVALUATOR_MODEL_NAME` | 評価用Geminiモデル名 | evaluator |
| `STEP1_MODEL` / `STEP2_MODEL` | persona_main_functionの各ステップで使うGeminiモデル名 | persona_main_function |
| `CF_CLIENT_ID` / `CF_CLIENT_SECRET` | Cloudflare Access（ELYZA呼び出し経路） | evaluator |
| `SMTP_USER` / `SMTP_PASSWORD` | 管理者招待メール送信（Gmailアプリパスワード） | evaluator |
| `OWNER_EMAIL` | 管理者ブートストラップ用メールアドレス | evaluator, CI/CD |
| `ADMIN_FRONTEND_URL` | 招待URL組み立て用フロントエンド基点URL | evaluator |
| `GCP_BILLING_EXPORT_TABLE` / `GCP_COST_SYNC_SECRET` | GCPコスト集計機能 | evaluator |
| `MONTHLY_BUDGET_JPY` / `GCP_PROJECT_ID` | コスト管理・GCPプロジェクト特定 | evaluator, persona_main_function |
| `GOOGLE_APPLICATION_CREDENTIALS` | GCPサービスアカウント認証 | 各種スクリプト |
| `OLLAMA_ENDPOINT` / `VLLM_ENDPOINT` / `VLLM_API_KEY` / `LLMJP_URL` | ローカル/リモート推論エンドポイント | batch_factory |
| `FIRESTORE_COLLECTION` | 書き込み先Firestoreコレクション名 | batch_factory |
| `K_SERVICE` | Cloud Run環境かどうかの自動判定用（GCPが自動注入） | evaluator |

### 主な設定ファイル
- `.env`（リポジトリルート、各アプリ内にも個別に存在）: 秘密情報。gitignore対象
- `pyrightconfig.json`: Pyright実行環境設定（`.venv`, `extraPaths`定義）
- `.pre-commit-config.yaml`: pre-commitフック（ruff, check-yaml, check-ast,
  check-added-large-files, 独自の`check_instructions_layout.py`）
- `packages/shared_core/alembic.ini` + `alembic/versions/`: DBマイグレーション
  （最新head: `f7a2c9e5b1d4_add_llmjp_pinch_hitter_fields.py`、2026-08-11付）
- `.github/workflows/*.yml`: CI/CD定義4本（§後述）
- `cloudbuild.yaml` / `cloudbuild.persona-router.yaml`: 手動Cloud Buildビルド定義
  （デプロイは含まない、ビルド+プッシュのみ）

### CI/CDワークフロー概要（`.github/workflows/`）
- `ci_pr_check.yml`: PR時、evaluatorのDockerイメージをビルドし脆弱性スキャン
  （CRITICAL/HIGHで失敗）。デプロイはしない
- `deploy_cloud_run.yml`: `main`へのpush時、WIF経由でビルド・脆弱性スキャン・
  Cloud Runデプロイ・Firebase Hostingデプロイまで実施（evaluatorのみ対象。
  persona_main_functionはこのワークフローの対象外、**未確認**: 別途自動デプロイがあるか）
- `pyright_check.yml`: PR時、`tests/`のpytest実行 → 変更行のみのPyright型チェック
- `cron_cleanup.yml`: 毎日UTC 18:00、`tools/cleanup_git_resources.py`でマージ済み
  ブランチ/worktreeを掃除

---

# 補足: リポジトリ構造上の注意点

- **`apps/batch_factory`は独立したgitリポジトリ**（own `.git`）であり、ルートリポジトリ
  からは`.gitmodules`無しの「埋め込みリポジトリ」（gitlink）として参照されている。
  正式なgit submoduleとしての初期化・更新手順は整備されていない状態。ルートで
  `git status`しても中の変更は`modified content`としか出ず、詳細は
  `git -C apps/batch_factory status`で個別に見る必要がある。
- **ドキュメントとコードの乖離に注意**: `apps/evaluator/PROJECT_CORE.md`はこのプロジェクトの
  「生きたドキュメント」として運用されているが、DB構成（Firestoreのみ、という記述）など
  一部実装と乖離した記述が確認された（§5参照）。コードとドキュメントが矛盾する場合は
  実コード（特に`packages/shared_core/nazokake_core/database.py`と`firestore_sync.py`の
  冒頭コメント）を優先すること。
- **過去の「1タスク1指示ファイル」運用の名残**: `archive/instructions_history/tools_instructions/`
  に、`NNN_claude_<slug>.txt`という命名で約280個の過去タスク指示ファイル（番号は歯抜けあり、
  概ね001〜401の範囲）が残っている。コミットメッセージや`PROJECT_CORE.md`中に
  `instructions/221`のような番号参照が現れることがあるが、これは当時のこの指示ファイル
  システムを指している（現在は現役の運用ではなく、アーカイブされた履歴）。
- 詳しい現状の実装状況・未解決課題・次のアクションは [`docs/handoff.md`](docs/handoff.md) を参照。
