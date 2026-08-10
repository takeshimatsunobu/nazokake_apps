# NAZOKAKE_APPS プロジェクト全体骨格マップ

> `structure_scanner.py`(os.walk + ast、Read-Only解析用・使用後削除)による自動抽出結果を基に、
> 各ドメイン・モジュールの役割を意味付けしたもの。生成日: 本レポート作成時点のリポジトリ状態に基づく。

---

## 1. ルート直下 `nazokake_apps/` — システム統括層

| ファイル | 役割 |
|---|---|
| `nazo_agent.py` | プロジェクト唯一の**オーケストレーター**。① `check_http_alive`/`_ensure_service_alive`/`startup_local_services` = ローカル環境(Ollama, Backend FastAPI:7800, Frontend dev_server:7300)のワンコマンド死活監視・自動起動。② `acd_*` 関数群 = AST精密抽出による静的解析ログの圧縮エンジン(ACD Engine)。③ `phase1_audit`〜`phase3_aider_execution` = 静的解析→Claude API翻訳→Aiderによる自動修正、という自己修復パイプライン本体。 |

このファイルが**5領域のうち唯一「他ドメインをコードから直接操作する」**モジュールであり、実質的に本ワークスペース全体の司令塔。ただし操作対象は`nazokake-evaluator`のみで、他2ドメインは範囲外(詳細は「気づき」参照)。

---

## 2. `nazokake-evaluator/` — プロダクト本体(なぞかけ生成・評価Webアプリ)

FastAPIバックエンド + 静的フロントエンドで構成される、実際に稼働するWebサービス。

- **`backend/api/routers/`**(公開APIの窓口): `generate`(AI生成)、`submission`(人間投稿)、`feed`(ユーザー/ゴールデンフィード配信)、`feedback`、`admin`、`board`(掲示板)、`metrics`(テレメトリ)。ルーターごとに機能を明確分離。
- **`backend/services/`**(ビジネスロジック): `generation.py`がGemini/ローカルLLM(ELYZA等)経由でなぞかけを生成する中核。`output_parser.py`がLLMの自由形式出力からJSONを頑健に抽出。`evaluation.py`は**現在空(トップレベル関数なし)** — 前回の調査で判明した`run_evaluation`未定義によるImportErrorの実体がここ。
- **`backend/models/schemas.py`**: Pydanticで8種のリクエスト/レスポンス型を定義し、API境界のデータ契約を明示。
- **`backend/core/`**: 設定(`config.py`)とグローバル例外ハンドラ。
- **`backend/scripts/`**: `extract_dpo_data.py`/`extract_rlhf_dataset.py`/`extract_sft_data.py`/`backfill_board.py`など、Firestoreの本番データを学習用データセット形式に変換するETL群。**評価用プロダクトDBと学習パイプラインを繋ぐ橋渡し**。
- **`frontend/public/dev_server.py`**: npm/フレームワークなしの素のstdlib `http.server`(no-cache版)。フロントエンドはビルドレスな静的HTML/JS/CSS構成。
- **`scripts/`(トップレベル、約30ファイル)**: GCPインフラ操作(`setup_gcp_l4_instance.py`, `wake_up_vm.py`, `dynamic_gcp_build.py`)、Firestoreデータ監査(`audit_firestore_data`, `diagnose_database`)、ローカルLLM実験(`local_gemma_api.py`, `train_local_gemma.py`)が混在する**運用・実験用の雑多スクリプト集**。
- **直下の`test_*.py`/`generate_context.py`等**: アドホックな検証・コンテキスト書き出しスクリプト。プロダクト構造には属さない。

---

## 3. `nazokakebatchfactory/` — 学習データ生成ファクトリー

なぞかけの学習データ(SFT/DPO/RLHF用)をLLMで自動生成・自己評価するバッチパイプライン。

- **`batch/main.py`**: パイプラインの実行エントリポイント(`process_generation`, `run`)。
- **`batch/llm_client.py`**: `GeminiGenerator`/`OllamaGenerator`/`LocalUnslothGenerator`を統一インターフェースで切り替える生成バックエンド抽象化層。
- **`batch/gemini_evaluator.py`**: 生成物をGemini APIで自己採点する評価器。
- **`batch/scorer.py`** + **`batch/persona.py`** + **`batch/trends.py`**: スコア計算、Big5人格プロンプトのバリエーション生成、時事トレンド収集によるネタの多様化——**生成品質・多様性を担保する3本柱**。
- **`batch/rag_retriever.py`**: 過去の生成物や参考データをRAGで検索し、生成プロンプトに注入。
- **`batch/firestore_writer.py`**: 生成結果をFirestoreへ永続化する出口。
- **`batch/schemas.py`**: `NazokakeGenerationOutput`/`Scores`/`PersonaMeta`/`TrendMeta`等——**ファクトリーが生成するデータの正式な型定義**。`nazokake-evaluator/backend/scripts`のETLが読み込む先はこのスキーマに準拠したFirestoreデータ。
- **ルート直下の`phase1_seed.py`→`phase2_generate.py`→`phase3_evaluate.py`**: 明確な3段階バッチパイプラインの実体(ただし全てBOM付きファイルでast解析がエラーになった。下記「気づき」参照)。
- **`unsloth_compiled_cache/`**: `unsloth`ライブラリが実行時に自動生成するトレーナーコード(GRPO/DPO/PPO/KTO等、約15ファイル・150関数超)。**手書きの自社コードではなくサードパーティのビルドキャッシュ**であり、プロジェクトの複雑度を測る上では除外すべきノイズ。

---

## 4. `Nazokake_localLLM/` — ローカルLLM実験領域

Pythonファイルは `run_auditor.py`(`pre_flight_check`含む)1本のみ。他ドメインと同名の監査スクリプトが置かれているのみで、ドメイン固有の実装(モデルファイル・バイナリ類)はast解析の対象外(非.py)のため今回のスキャンでは可視化されていない。現状は**最も薄い/実験初期段階のドメイン**と推測される。

## 5. `nazokake_lab/` — Pythonファイルなし

スキャン範囲内に`.py`ファイルが1つも存在しない。ノートブックやデータのみのサンドボックス、または未着手のプレースホルダーディレクトリの可能性が高い。

---

## 5領域間のデータ連携・依存関係に関する気づき

1. **オーケストレーターのカバレッジは`nazokake-evaluator`のみ**: `nazo_agent.py`が自動監視・自己修復するのはevaluatorだけで、`nazokakebatchfactory`と`Nazokake_localLLM`は完全に独立したスタンドアロン運用(手動起動のバッチジョブ)。「ワンコマンド起動」の対象範囲がプロジェクト全体ではなく1/5ドメインに留まっている。
2. **`run_auditor.py`が3ドメイン(evaluator/batchfactory/localLLM)に同一の関数構成でコピペ配置されている**: 共通パッケージ化されておらず、1箇所を修正しても他2箇所には反映されない。監査ロジックの改善が分散して形骸化するリスクがある。
3. **evaluatorとbatchfactoryはコード上は無関係だが、Firestoreスキーマで暗黙に結合している**: `batch/schemas.py`が定義するデータ形をfactoryが書き込み、`backend/scripts/extract_*_data.py`が同じコレクションを読み出す。直接のimport依存が無いため、片方でスキーマを変更しても静的には検知できず、実行時にのみ破綻する疎結合構造。
4. **`nazokakebatchfactory`直下の主要パイプラインファイル(`phase1_seed.py`等7本)がUTF-8 BOM付きで保存されており、`ast.parse`が例外を出す**: 実行自体はPython側で許容される可能性が高いが、静的解析ツール全般(本スキャナー含む)との相性が悪く、地味な技術的負債として残っている。
5. **`unsloth_compiled_cache/`はベンダーコードであり、リポジトリの「自社ロジック規模」を測る際にノイズとなる**: 今後の仕様書でコード量や複雑度に言及する場合はこのディレクトリを明確に除外すべき。



