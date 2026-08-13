# SYSTEM_DEEP_DIVE.md — なぞかけ道場 アーキテクチャ・リファレンス

> **目的**: このドキュメントは、外部LLM(Gemini)にプロジェクト固有のチャットボット知識
> ベースとして与えることを想定した、なぞかけ道場モノレポのアーキテクチャ・リファレンス
> である。すべての記述は、このドキュメント作成時点(HEAD `33ab466`, branch `main`,
> 2026-08-13)のリポジトリを実際にコードリーディングして確認した内容に基づく。未確認の
> 事項には明示的に「未確認」と記す。値を含む秘密情報(APIキー等)は一切含めない。
>
> 姉妹ドキュメント: リポジトリ直下の `CLAUDE.md`(セッション間引き継ぎ用の運用ドキュメント。
> 起動コマンド・テスト手順・環境変数一覧など、本書がカバーしない実務情報を持つ)。
> 本書との間で記述が食い違う場合は、両者とも「実コードを読んで確認したこと」を建前とする
> ドキュメントであるため、より新しい方(git blame / 更新日で判断)を優先し、最終的には
> 常に実コードを正とすること。

---

## 目次

1. システム全体像(3アプリ + shared_core + tools/エージェント基盤)
2. なぞかけ生成のデュアルAIパイプライン(evaluator / persona_router)
3. データ層: SQLite SSoT + Firestore Push同期
4. tools/ 配下の自律修復・MLOpsエージェント基盤(3層構造)
5. インフラ・CI/CD
6. 用語集(グロッサリー)
7. 主要な環境変数一覧(名前と用途のみ)

---

## 1. システム全体像

このリポジトリは、性質の異なる複数のアプリケーションが同居するモノレポである。

```
apps/
  evaluator/       本番Webアプリ(なぞかけ生成・11軸評価・フィード・管理コクピット)
  persona_router/  ペルソナ(語り手キャラクター)別なぞかけ生成マイクロサービス
  batch_factory/   オフラインの大量生成・モデル学習(DPO/SFT)パイプライン
                   ★別のgitリポジトリが埋め込まれている(gitlink)。本書のスコープ外。
  tactical_cic/    なぞかけと直接関係のない別サブシステム(bda_worker.py, mdmp_engine.py
                   等、軍事教義由来の命名)。public/cic_dashboard.html + public/js/cic_*.js
                   と内部的に配線されており孤立コードではないが、詳細は未調査。
packages/
  shared_core/     3アプリ共通の共有Pythonパッケージ nazokake_core
                   (DB, Firestore同期, few-shot, persona定義, パーサー等)
tools/             50以上の運用/MLOps/診断スクリプト群。中核は3層の自律修復エージェント基盤
                   (nazo_agent.py → agent_graph.py → mlops_pipeline_agent.py、§4参照)
workers/
  ondemand_elyza_worker.py  ユーザーのローカルGPU機でFirestoreジョブキューをポーリングし、
                             ELYZA(Ollama)生成をオンデマンド実行するワーカー
infra/             Docker Compose定義・検証環境・GCPエフェメラルVM関連スクリプト
run/               実行時生成物(監査ログ、デッドレター、実験DB、生存監視heartbeat等)。
                   tools/config.py の設計により、tools/ 自体は原則Read-Onlyに保たれ、
                   すべての可変な状態(state)はこのディレクトリへ分離される。
```

`apps/evaluator` が最も活発に開発されている本番アプリ、`apps/persona_router` は
2026-08-11に新規追加された新しいマイクロサービス(この監査時点で独自のCI/CD
`deploy_persona_router.yml` が構築済み)。`apps/batch_factory` は独立した `.git` を
持つ埋め込みリポジトリで、正式な git submodule ではなく git がいう「埋め込みリポジトリ」
(gitlink, mode 160000)として扱われている(**未確認**: なぜ独立リポジトリなのか、
意図的な設計かは不明)。

リポジトリ直下には他にも `Nazokake_localLLM/` という、これ自身が独立した `.git` を
持つ埋め込みディレクトリが存在する。中身は aider/RAG関連の実験的なプロトタイプに見え
(`RAG_implementation_guide.md`, `.aider.conf.yml` 等)、コードベースのどこからも参照
されていない。本書のスコープ(`apps/`, `packages/`, `tools/`, `workers/`, `scripts/`)
の外にあり、かつ埋め込みリポジトリという性質上、安全な調査・整理には追加の確認が必要
(**未確認**、現状に手を付けていない)。

### アプリ間の依存関係

3アプリ(evaluator / persona_router / batch_factory)はすべて `packages/shared_core`
を `nazokake-core` というローカルパス依存(`uv` の `editable = true`)として参照する。
これによりDB接続・Firestore同期・persona定義・few-shotプールなどのロジックの重複を
避けている。ただしこの設計のため、各アプリの Docker ビルドはリポジトリルートを
ビルドコンテキストにする必要があり(`apps/persona_router/Dockerfile` 等)、
Cloud Build の構成が単純な「アプリディレクトリ単体ビルド」にできない制約を生んでいる。

---

## 2. なぞかけ生成のデュアルAIパイプライン

### 2.1 apps/evaluator(本番Webアプリ)

- **フロントエンド**: Vanilla JS の完全 MVC 分離 SPA。Controller(`app.js`)は DOM 操作を
  一切行わず、API通信・ポーリング・イベント委譲のみを担当する。View(`ui/*.js`)に
  DOM操作を完全にカプセル化。
- **バックエンド**: FastAPI。`api/routers/*.py` にドメイン別ルーターが分割されている
  (旧 `endpoints.py` を解体、14ファイル)。`/generate` は即座に `task_id` を返し、
  背景タスクで Gemini と ELYZA を `asyncio.gather` で並走発火させるノンブロッキング設計。
- **Tier 1(ローカル・おまけ)**: ELYZA 8B(`elyza:8b`)。ローカルの Ollama 経由で呼び出す。
- **Tier 2(クラウド・主軸)**: Gemini(生成・11軸ブラインド評価)。構造化出力(JSON Schema)
  の強制適用あり。
- **best-of-1 アルゴリズム(「一発入魂」)**: `apps/evaluator/backend/services/generation.py`
  で確認済み。以前は best-of-N(N=3、`workers/ondemand_elyza_worker.py` 側で3候補を
  並行生成し最高得点を選抜、DPO選好ペアとして記録)方式だったが、`_OLLAMA_SEMAPHORE`
  (`asyncio.Semaphore(1)`)による直列化のため N 並行生成の効果自体が実質失われていた
  ことが判明し、1回の生成のみを試みる best-of-1 へ変更された(コミット `42a2297`)。
  詳細は §6 グロッサリーの「best-of-1 / best-of-3」参照。
- **ELYZA出力へのGemini混入禁止**: 同じくコミット `42a2297` で、ELYZA生成が失敗した際に
  黙って Gemini の結果へフォールバックする挙動を廃止し、明示的に例外を送出するよう変更。
  「ELYZAの出力」というラベルのデータに実際には Gemini の出力が混入するデータ完全性の
  問題を解消するため。

### 2.2 apps/persona_router(ペルソナ別生成マイクロサービス)

- `api/routers/generate.py` が `POST /v1/generate` の中核オーケストレーション
  (Step1推定 → Step2生成)。
- `services/step1_estimation.py`: お題単体の属性推定(persona非依存)。Firestoreキャッシュ
  あり(`services/step1_cache.py`、コレクション名は `STEP1_CACHE_COLLECTION`)。
- `services/step2_generation.py`: ペルソナを反映した生成。Route A(正常入力)/
  Route B(無効入力へのエンタメ的切り返し)に分岐。Few-shot注入あり。
- `services/penalty.py`: 荒らし対策の段階的ブロック(`user_penalties.blocked_until`)。
  `api/routers/unlock.py` がブロック解除リクエストの受付を担当(実際の解除は運営の手動
  操作)。
- `services/cost_logging.py`: Gemini呼び出しのコスト/レイテンシ計測。
- `main.py` は `apps/evaluator/backend` と同じ DDD 規約(api/routers, models, services)
  に従う。起動時のカレントディレクトリが `apps/persona_router` であることが前提
  (絶対import規約のため)。

---

## 3. データ層: SQLite SSoT + Firestore Push同期

`packages/shared_core/nazokake_core/database.py` の冒頭コメントで明言されている設計:

> 「Local-First アーキテクチャにおける『絶対的な正(Local SSoT)』であるローカルSQLite
> データベース」

- ローカル/Cloud Run上のSQLite(既定ファイル名 `nazokake_local.db`、
  環境変数 `NAZOKAKE_DB_PATH` で上書き可能)が正であり、Firestoreへは
  `firestore_sync.py` により一方向Push(+起動時Pull復元)される。
- 複数プロセス/ワーカーからの同時アクセス時の `SQLITE_BUSY` を二段構えで防止:
  1. 接続確立ごとに `PRAGMA journal_mode=WAL` / `synchronous=NORMAL` / `busy_timeout`
     を強制(プロセス間の並行性・再試行を確保)。
  2. プロセス内の全DB操作を単一の "Serialized Writer" タスクへ集約し直列実行
     (プロセス内の排他制御)。`apps/batch_factory` 側の同期コード呼び出し元は
     `sync_*` 関数群経由でこのキューへタスクを push する。
- `apps/evaluator/PROJECT_CORE.md`(ドキュメント)は「データベースはFirestoreのみ、
  クライアントからの直接Read/Writeは完全封鎖」と記述しているが、これは実装(SQLite SSoT
  + Push同期)と乖離した古い記述である可能性が高い。実コード(`database.py` /
  `firestore_sync.py` の冒頭コメント)を優先すること。掲示板機能(`board.py`)のみが
  Firestore直接読み書きを許可された明示的な例外。
- **未配線の可能性がある既知の懸念**: `packages/shared_core/nazokake_core/utils.py`
  の `_normalize_for_sqlite()` は「Firestoreの時刻データをSQLiteのDateTimeカラム用に
  正規化する」関数で、ドキュメント上は「過去の強制的な文字列キャストによる不等号比較の
  バグを解消した」とあるが、リポジトリ全体を検索してもこの関数を呼び出している箇所が
  見つからない。一方 `firestore_sync.py` の同期判定ロジック(`remote_updated_at >
  local_updated_at` の比較)はこの正規化を経由していないように見える。この関数が
  導入されるに至った不等号比較バグが実際に解消済みかどうかは **未確認**。

---

## 4. tools/ 配下の自律修復・MLOpsエージェント基盤(3層構造)

このリポジトリには、コードベース自身のバグを検知・自己修復し、その修復軌跡を学習データ
として蓄積して自らを改善する、3層構造の自律エージェント基盤が存在する。

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: tools/nazo_agent.py  (オーケストレーター/常駐デーモン)     │
│   - ユーザーの自然言語指示を受け取る対話ループ                     │
│   - Phase 0-4: ruff自動修復 → 静的解析監査 → タスク生成 → 実行 → 再監査 │
│   - engine="claude" / "ollama" のいずれかへディスパッチ            │
└───────────────┬─────────────────────────────┬─────────────────┘
                │ engine=claude                │ engine=ollama
                ▼                              ▼
   Claudeパイプライン(nazo_agent.py内)   ┌─────────────────────────────┐
   Tool Calling + Pydantic +           │ Layer 2: tools/agent_graph.py │
   自己修正ループ + libcst AST置換      │   LangGraphによる自律修復ループ│
                                        │   (Hot Loop: Qwen単一モデル・  │
                                        │    マルチロール)                │
                                        └───────────────┬─────────────┘
                                                        │ 成功修復のたびに
                                                        │ run/dataset/agent_sft.jsonl
                                                        │ へ1行追記(フライホイール)
                                                        ▼
                              ┌───────────────────────────────────────┐
                              │ tools/mlops_trigger.py (イベント駆動キック) │
                              │  条件B: agent_sft.jsonl行数が閾値以上なら  │
                              └───────────────┬─────────────────────────┘
                                              ▼
                              ┌───────────────────────────────────────┐
                              │ Layer 3: tools/mlops_pipeline_agent.py  │
                              │   Nazo-Agent自身(Qwen)のLoRA再学習パイプ │
                              │   ライン。定量ゲート通過時のみデプロイ承認 │
                              └───────────────────────────────────────┘
```

### 4.1 Layer 1: `tools/nazo_agent.py`(オーケストレーター)

- 常駐デーモンとして起動し、標準入力から複数行の自然言語指示を受け取るループ
  (`--prompt <file>` でバッチ1回実行モードも可)。
- `_route_target_domain()`: 指示文中のキーワード(「バッチ」「工場」「batch」「factory」
  「パイプライン」「unsloth」)で対象領域を `apps/batch_factory` に切り替え、それ以外は
  既定で `apps/evaluator` を対象とする(自然言語→ターゲットディレクトリのルーティング)。
- **Phase 0**: ruffによるネイティブ自動修復(LLM推論前の事前クリーンアップ)。
- **Phase 1 / 4**: ruff + mypy(dmypyデーモン経由)による静的解析監査。ACDエンジン
  (Anomaly Compression & Deduplication、後述グロッサリー参照)でエラーログをAST単位に
  圧縮する。
- **Phase 1.5**: ローカルの Gemma(`gemma4:12b`)による中間評価(トリアージ)。AST圧縮済み
  の「客観的事実」のみを見せ、Claudeへ渡す前のグラウンディング強化として機能する。
- **Phase 2**: `engine="claude"` の場合、Claude(`claude-sonnet-5`)の Tool Calling
  (`tool_choice` 強制)で「AST置換設計」(修正方針の自然言語指示のみ、実装コードは書かない)
  へ翻訳する。Pydanticスキーマ検証失敗時は最大3回の自己修正ループ、それでも失敗したら
  タスク0件で縮退運転しデッドレターへ記録する。
- **Phase 3**: 実際のコード生成をローカルCoder(Ollama)へ委譲し(FinOpsのためClaudeは
  コードそのものは書かない設計)、`tools/ast_modifier.py` による libcst 安全AST置換で
  適用する。
- `engine="ollama"`(既定)の場合は Phase 2 を経由せず、Layer 2(`agent_graph.py`)の
  `run_self_repair()` へ直接委譲する。
- 修正は原則 `main` へ直接コミット・Pushされず、専用ブランチ上の PR ドラフトとして提出
  される(`_create_and_open_pr`、`gh pr create --draft`)。
- Dead Letter Queue: 自己修正が尽きた失敗内容を `run/audit_reports/dead_letters/` へ
  PIIマスキング済みJSONとして保存する(`sanitize_pii()`)。

### 4.2 Layer 2: `tools/agent_graph.py`(LangGraph自律修復ループ)

VRAM 8GB(RTX 4060)の物理制約下で「複数モデル同時常駐は絶対に行わない」という制約の
もと設計された、単一モデル・マルチロール(シングルモデル・マルチロール)の自己修復
ループ。LangGraphの `StateGraph` でノード遷移を管理する(`AuditState` という
`TypedDict` が状態を保持)。

**ノード構成**(`build_graph()` で `graph.add_node("名前", 関数)` により文字列キーで
登録される。直接の関数呼び出しは存在しないため、grepだけでは呼び出し元が見つからない
ことに注意 — これは意図的なLangGraphのルーティングパターンである):

| ノード名 | 役割 |
|---|---|
| `supervisor` | 【現場監督】エラーログ+対象コードから原因・修正方針を診断(修正コードは書かない) |
| `craftsman` | 【職人】診断に基づきAST置換用JSONを1件出力。Ollamaのネイティブ文法制約付き生成(`format=<JSON Schema>`)で構造を強制、Few-shot注入で質を担保 |
| `validate` | JSON文字列をパース・Pydantic検証。失敗時は`craftsman`へ差し戻し(最大`MAX_JSON_RETRIES=3`回) |
| `apply` | 検証済みJSONを`tools/ast_modifier.py`へサブプロセス委譲し、実ファイルへAST置換適用 |
| `typecheck` | 適用後・コミット前のPyright型チェックゲート。エラー検出時は`craftsman`へ差し戻す自己修復ループ |
| `cto_node` | Qwen自身が申告した不確実性(confidence_score不足/requires_escalation)を受け、Claude(`claude-sonnet-5`)へレビュー・改善案生成を委譲 |
| `sandbox_verify` | CTOの修正案を`git worktree`で隔離した専用ブランチへ適用・型チェック・ベンチマーク検証し、人間レビュー用PRドラフトを生成。**この経路のみ意図的にPush/PR作成を自動化せず人間の手動操作に委ねる**(2026-08-01にユーザー承認済みの意図的設計、指示書#270で再確認) |
| `gemma_fallback` | サーキットブレーカー作動時のみ遷移。Qwenを明示的にVRAMアンロード後、Gemma(`gemma4:12b`)へ最終エスカレーションし失敗原因を分析、デッドレター保存後に処理を一時停止(Suspend) |
| `reporter` | 最終サマリー出力(グラフの終端) |

- **VRAM排他制御の要**: Hot Loop(`supervisor`→`craftsman`→`validate`→`apply`→
  `typecheck`)では Qwen(`qwen2.5-coder:7b`)単一モデルをロードしたまま維持し、
  ロード/アンロード切り替えを一切行わない。Gemmaへのエスカレーション遷移時のみ、
  `keep_alive=0` で明示的にQwenをアンロードしてからGemmaをロードする(このI/O
  ペナルティはこの経路でのみ許容される)。
- **Test-Driven Escalation Gatekeeper**: `nazo_agent.py::verify_logic_with_pytest()`
  が、Ollamaの「文法的には正しいが論理が破綻したコード」を静的解析では検知できない
  ケースに対し、`pytest --testmon -n auto`(変更影響テストの選択的・並列実行)で決定論的
  に検証する。失敗時はClaudeパイプラインへエスカレーションする。
- **Experience Replay**: `cto_node` は `tools/knowledge_retriever.py` により過去の
  指示書(`archive/instructions_history/`)から関連度上位の教訓を検索し、CTOプロンプト
  へ動的に注入する軽量ローカルRAG。

### 4.3 Layer 3: `tools/mlops_pipeline_agent.py`(Nazo-Agent自身の再学習)

Layer 1/2 の自己修復ループが蓄積した「推論軌跡」(`run/dataset/agent_sft.jsonl`、
成功修復のたびに1行追記)を使い、Qwen(`qwen2.5-coder:7b`)自体をLoRA再学習する
MLOpsパイプライン。

1. **Pre-flight GPU Cleanup**: 前回異常終了のゾンビプロセスを掃除。
2. **VRAMグローバルロック取得**: `apps/evaluator/backend` や姉妹パイプライン
   `tools/mlops_pipeline_nazo.py`(なぞかけ生成モデル自体の学習、こちらは
   Gemini/ELYZAが生成したなぞかけのDPO/SFT候補を対象とする別系統)と競合しないよう、
   指数バックオフでポーリング待機してから取得する。
3. **データ抽出**: `tools/extract_agent_sft.py` をサブプロセス実行
   (`tolerate_failure=True`。★このファイルは現在リポジトリに存在しない、§7参照)。
4. **学習**: `tools/train_agent_model.py`(内部で共用コア `tools/train_unsloth_core.py`
   を呼ぶ)。
5. **定量ゲート**: `tools/benchmark/run_benchmark.py` の結果を評価し、
   Success Rate Delta >= 0 かつ Code Complexity 増加率 < 10%(`settings.
   quality_gate_complexity_max`)を両方満たした場合のみ「学習成功およびデプロイ承認」
   として正常終了する。Success Rate が計測不能な場合は安全側に倒して不合格とする。
6. 実行結果は `tools/mlops_experiments_db.py` 経由で `tools/mlops_experiments.db`
   (実験管理DB)へ不変ログとして記録され、`trigger_state`(pipeline_id="agent")の
   claimを解放する。

**起動トリガー**: `tools/mlops_trigger.py` が条件A(なぞかけDPO/SFT候補が閾値以上)/
条件B(Nazo-Agent成功修復ログが閾値以上)をステートレスに評価し、DBの
`trigger_state` テーブル(CASパターンで排他制御+クールダウンをアトミックに判定)経由で
claim を奪取できた場合のみ `tools/deploy/run_ephemeral_pipeline.ps1` 経由でエフェメラル
GCP VM をキックする(VM起動→SSH開通待ち→コード転送→パイプライン同期実行→VM自律停止
の全ライフサイクルを待機、Windows経路)。`shadow_mode`(既定 `True`)が有効な間は実際の
DB claim・VMキックを一切行わず判定結果のみをログする安全弁。

**★重要な既知の不具合**: `tools/mlops_trigger.py` はモジュールインポート時に
`from tools.extract_dataset import _fetch_candidates` を実行するが、
`tools/extract_dataset.py` は本書作成時点で**リポジトリに存在しない**(コミット
`b2b22d9`「chore(infra): enforce CI/CD SSoT, remove backdoor, setup GH actions」で
`tools/extract_agent_sft.py` と共に削除済み。このコミットはHEADの祖先)。このため
`tools/mlops_trigger.py` は現在**インポート時点で `ModuleNotFoundError` を送出し、
起動すら出来ない**ことを実際に確認済み。Layer 3 全体(条件A/B双方のトリガー)が現時点で
機能停止していることを意味する。詳細は本タスクの技術的負債レポートを参照。

---

## 5. インフラ・CI/CD

- **本番Webアプリ(evaluator)**: GCP Cloud Run(バックエンド) + Firebase Hosting
  (フロントエンドSPA)。
- **persona_router**: 独自の `apps/persona_router/Dockerfile` + `cloudbuild.
  persona-router.yaml` + `.github/workflows/deploy_persona_router.yml` を保有
  (このリポジトリ検分時点で確認。CLAUDE.md の記述時点ではこのワークフローの有無が
  「未確認」とされていたが、本書作成時点では存在を確認済み)。
- **VRAM排他制御と `--workers 1` 固定**: `run_api.ps1` はローカルGPU (RTX 4060 8GB) で
  ELYZA(Ollama)を安全に動かすため、`uvicorn` の `--workers` を常に1へ固定し、複数
  ワーカー指定を拒否する(VRAM排他制御が単一プロセス前提のため)。
- **オンデマンドELYZAワーカー**: `workers/ondemand_elyza_worker.py` がユーザーの
  ローカルPC上でFirestoreジョブキューをポーリングし、生成結果を書き戻す。ジョブ失敗時は
  即座に `dead_letter` 化(リトライキュー方式は撤廃済み)。クラウド側は一定時間待って
  Gemini Flash Liteへの「代打」フォールバックへ切り替える。
- **CI/CDワークフロー**(`.github/workflows/`): `ci_pr_check.yml`(PR時のDockerビルド+
  脆弱性スキャン、デプロイなし)、`deploy_cloud_run.yml`(mainへのpush時、evaluatorの
  ビルド・脆弱性スキャン・Cloud Run/Firebase Hostingデプロイ)、
  `deploy_persona_router.yml`(persona_router用の同種デプロイ)、
  `pyright_check.yml`(PR時、`tests/`のpytest実行→変更行のみのPyrightラチェット型検査)、
  `cron_cleanup.yml`(毎日UTC 18:00、マージ済みブランチ/worktreeの掃除)。
- **型チェックのラチエット方式**: `tools/pyright_tool.py --gate` は「変更行のみ」を
  検査する差分ブロック方式。導入時点で `tools/` 配下だけで既存338件のエラーがあった
  ため、全件ブロックではなくこの方式を採用した経緯がある(CLAUDE.md記載)。

---

## 6. 用語集(グロッサリー)

- **SSoT(Single Source of Truth)**: このプロジェクトでは主に2つの文脈で使われる。
  (1) データの正 = ローカルSQLite(`nazokake_local.db`)、Firestoreはレプリカ
  (§3参照)。(2) 仕様の正 = `SSoT_architecture.md`(存在すれば `nazo_agent.py` /
  `agent_graph.py` のプロンプトへ動的注入される「絶対的仕様書」。本書作成時点では
  リポジトリに存在しない。参照側は未存在時に空文字へフォールバックする設計になっている
  ため、この点自体はクラッシュを起こさない)。
- **AST-based code replacement(AST置換)**: `tools/ast_modifier.py` が
  `libcst`(Concrete Syntax Tree操作ライブラリ)を用いて、関数/クラス単位でソース
  コードを安全に置換する仕組み。正規表現による文字列置換ではなく構文木レベルで操作する
  ため、インデント崩れや意図しない範囲の書き換えを防ぐ。Layer 1(Claudeパイプライン)・
  Layer 2(`apply_node`)の双方が最終的にこのスクリプトへ委譲する。
- **ACDエンジン(Anomaly Compression & Deduplication、推定)**: `nazo_agent.py` 内の
  `acd_*` 関数群。エラーログの重複行を圧縮する Phase 1(`acd_phase1_dedup`)と、AST解析
  でエラー発生箇所を関数/クラス単位のソースへ機械的にグラウンディングする Phase 2/3
  (`acd_ast_compress`, `acd_ast_context_for_file`)から成る。LLMへ渡すコンテキストの
  肥大化(ハルシネーション・APIコスト増)を防ぐ目的。
- **LangGraph state management**: `tools/agent_graph.py` が `langgraph.graph.
  StateGraph` を用いて実装する、ノード間で `AuditState`(`TypedDict`)を受け渡す
  有向グラフ型のワークフロー管理。各ノード関数は状態の一部を更新する `dict` を返し、
  `Annotated[list[str], operator.add]` のような型注釈でリストは自動的に累積(追記)
  される。文字列キーでノードを登録・遷移させるため、静的な import グラフだけでは
  呼び出し関係が見えない(本書執筆時のdead-code調査で重要な注意点だった)。
- **VRAM排他制御/防弾化**: RTX 4060(VRAM 8GB)という物理制約下で、複数の大規模モデルを
  同時常駐させないための設計原則群の総称。(1) `apps/evaluator/backend` の
  `_OLLAMA_SEMAPHORE = asyncio.Semaphore(1)` によるOllama呼び出しの直列化、
  (2) `run_api.ps1` の `--workers 1` 固定、(3) `agent_graph.py` のシングルモデル・
  マルチロール設計 + `keep_alive=0` によるモデル切替時の明示的VRAM解放、
  (4) `tools/mlops_common.py` の `VRAM_LOCK_PATH`(`.vram.lock`)によるアプリ本体
  ⇔ MLOpsパイプライン間のグローバルファイルロック、の4つが該当する。
- **best-of-1 / best-of-3**: なぞかけ生成の候補選抜アルゴリズム。best-of-3(旧)は
  同一お題に対しELYZA生成をN=3回並行実行し最高評価スコアの候補を採用、残りをDPO選好
  ペア(勝者/敗者)としてログする方式。best-of-1(現行、「一発入魂」)は1回のみ生成する
  方式。`_OLLAMA_SEMAPHORE(1)` による直列化のためN並行実行の並列性が実質失われていた
  ことが判明し、コミット `42a2297` でレイテンシ最適化のため置き換えられた
  (ポーリング間隔も8.0秒→2.0秒等に短縮)。
- **Dead Letter Queue(デッドレター)**: 自己修復ループが最大リトライ回数に達し失敗した
  際、失敗時点の全文脈(システムプロンプト・会話履歴・最終エラー・LLMの生の応答)を
  `run/audit_reports/dead_letters/` へ構造化JSONとして保存する仕組み。PII(メール
  アドレス・APIキー・電話番号らしき数字列)は書き込み前に正規表現でマスキングされる
  (`sanitize_pii()`)。事後分析による可観測性強化が目的で、失敗記録自体は貴重な学習
  シグナルとして扱われ、削除・隔離の対象にしてはならない。
- **シャドウモード(shadow_mode)**: `tools/config.py::ToolsSettings.shadow_mode`
  (既定 `True`)。有効な間、データフライホイール(`mlops_trigger.py` /
  `nazo_agent.py` / `agent_graph.py` の自己修復・学習ループ)は実際のDB状態更新
  ・エフェメラルVMキック・Gitコミットを一切行わず、実行されたはずの内容を
  `run/shadow_mode_log.jsonl` へ記録するのみに留める段階的始動措置。
- **CTOエスカレーション**: Layer 2(`agent_graph.py`)内で、Qwen(職人ロール)が
  自己申告した `confidence_score` が閾値(既定0.8、`settings.
  escalation_confidence_threshold`)を下回るか `requires_escalation=True` を
  申告した場合に、クラウド上位モデル(Claude)へ修正案のレビュー・改善を委譲する経路。
  Gemmaフォールバック(形式面=JSONスキーマ検証の失敗が原因)とは独立した、内容面の
  不確実性に基づく別のエスカレーション経路。
- **6次元定量評価ゲート**: `tools/benchmark/run_benchmark.py::evaluate_6d_quality_gate()`
  が判定する、Nazo-Agentの本番稼働可否を客観的に判定する基準。Success Rate、
  Regression Rate、Max Retries、Blast Radius、Code Complexity増加率、そして
  「時間対品質パリティ」(CTOエスカレーションのlatencyがQwen単独解決の平均latencyの
  何倍まで許容されるか)の6軸から成る。
- **Serialized Writer**: `nazokake_core/database.py` が実装する、プロセス内の全DB
  書き込みを単一の非同期タスクへ集約し直列(1件ずつ)に実行するパターン。SQLiteの
  `SQLITE_BUSY` をプロセス内で構造的に防ぐ。

---

## 7. 主要な環境変数一覧(名前と用途のみ、値は含まない)

CLAUDE.md にも同様の一覧があるが、本書はエージェント基盤(tools/)寄りの変数を含めて
再掲する。

| 変数名 | 用途 | 主な使用箇所 |
|---|---|---|
| `GEMINI_API_KEY` | Gemini API認証 | evaluator, persona_router, batch_factory 共通 |
| `ANTHROPIC_API_KEY` | Claude API認証(Layer 1のClaudeパイプライン・Layer 2のCTOエスカレーション) | tools/nazo_agent.py, tools/agent_graph.py |
| `NAZOKAKE_DB_PATH` | SQLite DBファイルの絶対パス(SSoT、既定 `nazokake_local.db`) | shared_core, evaluator, workers共通 |
| `VRAM_LOCK_PATH` | ELYZA(Ollama)呼び出し排他制御ロックファイルパス(既定 `.vram.lock`) | evaluator, workers, tools/mlops_common.py |
| `OLLAMA_HOST` | Ollamaクライアントの接続先(既定 `http://127.0.0.1:11434`)。サーバーbind用アドレス(`0.0.0.0`等)を設定するとFail-Fastで拒否される | tools/config.py 経由で各tools/*.pyが参照 |
| `LLMJP_MODEL` | ELYZA/LLM-JPモデル名(既定 `elyza:8b`) | evaluator |
| `EVALUATOR_MODEL_NAME` | 評価用Geminiモデル名 | evaluator |
| `STEP1_MODEL` / `STEP2_MODEL` | persona_routerの各ステップで使うGeminiモデル名 | persona_router |
| `CF_CLIENT_ID` / `CF_CLIENT_SECRET` | Cloudflare Access(ELYZA呼び出し経路) | evaluator |
| `SMTP_USER` / `SMTP_PASSWORD` | 管理者招待メール送信(Gmailアプリパスワード) | evaluator |
| `OWNER_EMAIL` | 管理者ブートストラップ用メールアドレス | evaluator, CI/CD |
| `GCP_BILLING_EXPORT_TABLE` / `GCP_COST_SYNC_SECRET` | GCPコスト集計機能 | evaluator |
| `MONTHLY_BUDGET_JPY` / `GCP_PROJECT_ID` | コスト管理・GCPプロジェクト特定 | evaluator, persona_router |
| `GOOGLE_APPLICATION_CREDENTIALS` | GCPサービスアカウント認証 | 各種スクリプト |
| `HF_TOKEN` | Hugging Face認証 | batch_factory学習パイプライン(スコープ外) |
| `MAX_ERROR_LOG_LINES` / `MAX_TOTAL_CONTEXT_CHARS` | Cognitive Load Auditor(Layer 1)の閾値。既定300行・40000文字 | tools/nazo_agent.py |
| `NAZO_AGENT_ENGINE` | Layer 1のディスパッチ先エンジン既定値(`ollama`/`claude`) | tools/nazo_agent.py |
| `SHADOW_MODE` | シャドウモードの有効/無効(既定 `true`) | tools/config.py 経由 |
| `ALERT_WEBHOOK_URL` | 異常終了・定量ゲート不合格時の通知Webhook(SecretStrで保持、ログ非露出) | tools/mlops_common.py |
| `MLOPS_TRIGGER_NAZO_THRESHOLD` / `MLOPS_TRIGGER_AGENT_THRESHOLD` | tools/mlops_trigger.pyの発火閾値(既定500/50) | tools/config.py 経由 |
| `MLOPS_TRIGGER_COOLDOWN_HOURS` / `MLOPS_TRIGGER_STALE_AFTER_HOURS` | パイプライン起動のクールダウン/ゾンビ回収時間 | tools/config.py 経由 |
| `API_DEV_PORT` / `FRONTEND_DEV_PORT` | ローカル開発サーバーのポート(SSoT化、既定7800/7300) | tools/config.py, run_api.ps1 |
| `K_SERVICE` | Cloud Run環境かどうかの自動判定用(GCPが自動注入) | evaluator |

---

*本書はこの監査セッション内で実施した静的コード調査(git grep によるリポジトリ全体の
参照グラフ確認、主要ファイルの全文読解、`import` の実動作確認)に基づいて作成された。
`apps/batch_factory`(別リポジトリ)と `apps/tactical_cic`(CLAUDE.mdが明示的に
調査範囲外としている別サブシステム)は意図的にスコープ外としている。*
