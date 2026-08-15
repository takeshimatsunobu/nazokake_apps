# なぞかけ道場プロジェクト ～ハイブリッド・デュアルAIアーキテクチャ～

## 1. プロジェクトの目的と世界観
- **目的**: 「ELYZA（ローカル/Tier1）」と「Gemini（クラウド/Tier2）」を連携させたデュアルAIパイプラインを構築し、高度な日本語表現とユーモアを備えたなぞかけ自動生成・評価システムを開発する。
- **世界観**: 「和風スチームパンク（桜×抹茶×鉄色・真鍮色）」。ねづっち氏非公認の学術的AIプロジェクトであることを明示。
- **ユーザー体験**: ユーザーが遊びながらAIを育てる（RLHF: 人間からのフィードバックによる強化学習）プラットフォーム。

## 2. システム・アーキテクチャとインフラ制約
- **本番Webアプリ**: GCP Cloud Run (バックエンド FastAPI) + Firebase Hosting (フロントエンド SPA)。
- **推論インフラの絶対制約 (ピボット済)**: GCPのGPU枯渇（L4/T4全滅）のため、バッチ工場もWebアプリも、すべての推論処理を「ローカルPC（RTX 4060 8GB / Ollama）」に集約する完全ローカル・パイプラインへとピボット済み。AIエージェントはGCP VMへ接続しようとするスクリプトを書いてはならない。
- **データベース（Local-First、persona_feature_plan_v3.md Phase1〜3で確立）**: 「Firestoreのみ」ではない。ローカルSQLite（`nazokake_items`ほか、`packages/shared_core/nazokake_core/database.py`）を**絶対的な正（SSoT）**とし、Firestoreへは非同期の**一方向Push**（＋起動時の**Pull復元**）で同期するバックアップレプリカ構成。同期対象は`nazokake_items`単体ではなく、`audit_logs`（監査証跡）・`trigger_state`・`quality_circuit_breaker_state`・`research_articles`を加えた計5テーブル（`firestore_sync.py`のマルチコレクション対応、Phase1）。クライアントからのFirestore直接Read/WriteはDeny-Allのままだが、**掲示板機能（`board.py`）のみ明示的な例外**としてFirestore直接読み書きを許可している。
- **語り手ペルソナはFirestoreがSSoT（Phase4〜6で新設）**: なぞかけの「語り手」を表す `narrator_personas` / `narrator_persona_versions` はSQLiteに実体を持たず、Firestoreをそのまま正とするネイティブなコレクション（`packages/shared_core/nazokake_core/narrator_personas.py`が書き込み口を集約、内容ハッシュによる不変バージョニング）。組み込み10体＋センチネル`"No_Data"`に加え、`apps/persona_main_function`のマイペルソナ機能でユーザーが作成したカスタムペルソナも同じコレクションに同居する。姉妹アプリ`apps/persona_main_function`はこのFirestoreネイティブ構成を全面的に採用しており、evaluatorのようなSQLite SSoTを持たない。

## 3. フロントエンド (完全MVC分離 SPA)
- **Controller (`app.js`)**: DOM操作（画面の直接書き換え）を完全に排除。API通信・ポーリング・イベント委譲（Event Delegation）による交通整理のみを担当する純粋な司令塔。
- **View (`ui/*.js`)**: `result.js`, `feed.js`, `form.js`, `tabs.js`, `toast.js` 等に完全分割。DOM操作はすべてここにカプセル化されている。
- **State & API (`state.js`, `api.js`)**: アプリの状態管理と、fetch等を用いたバックエンドとの通信（エラーハンドリング含む）を独立管理。
- **UXの極意 (Progressive Disclosure)**: Geminiの生成・評価を先行表示し、裏側で遅延するELYZAの生成結果を「おまけ」としてフェードインさせる非同期UIの確立。

## 4. バックエンド (DDD再編 FastAPI)
- **ドメイン別ルーター (`api/routers/*.py`)**: 肥大化した `endpoints.py` を完全解体。`generate.py`, `feed.py`, `submission.py`, `metrics.py`, `admin.py` など機能別に分割・DI（Depends）化。
- **非同期並行パイプライン**: `/generate` は即座に `task_id` を返し、背景タスクで Gemini と ELYZA を `asyncio.gather` で並走発火させるノンブロッキング設計。
- **エラー制圧基盤**: FastAPIのグローバル例外ハンドラと、`Loguru` による構造化ロギングを実装し、サイレント・デスを根絶。

## 5. デュアルAIルーティングと11軸評価
- **Tier 1 (ローカル・おまけ)**: ELYZA 8B (`elyza:8b`)。Webアプリ・バッチ工場ともにローカルのOllama経由で呼び出す純国産モデル。VRAM 8GBの制約を考慮し、呼び出し時には過負荷（OOM）を防ぐための安全装置を設けること。
- **Tier 2 (クラウド・主軸)**: 生成は爆速の `gemini-3.5-flash`、11軸ブラインド評価は極めて高度な推論力を持つ `gemini-3.1-pro-preview` を採用。
- **最強の鑑定士**: 学術的ルーブリックに基づく11軸評価と、構造化出力（JSON Schema）の強制適用。

## 6. MLOps (RLHF/DPOデータパイプラインとモデレーション)
- **モデレーション検問所**: 一般ユーザーが「道場破り（フィード）」や「生成画面」で評価・コメント（`gen_eval:*`）を付けた瞬間、裏側で `is_user_edited = True` が刻印され、管理コックピットの「承認待ち」へ自動送致される荒らし対策パイプライン。
- **デュアル承認フロー**: 管理画面で Gemini と ELYZA 両方の処遇（承認・棄却など）が決定（`resolved`）したタイミングで初めて一般フィードへ公開される。
- **3層データセット基盤（persona_feature_plan_v3.md Phase8で確立）**: 学習データを「構造」「反応」「訂正」の3層に分離し、`packages/shared_core/nazokake_core/dataset_envelope.py`が定義する共通エンベロープ（`dataset_layer`/`source_ref`/`narrator_persona_id`/`narrator_persona_version_id`/`data_origin`/`owner_uid`/`created_at`/`payload`）で統一的に扱う。
  - **第1層（構造）**: `tools/extract_training_data.py`（SFT）・`apps/evaluator/backend/scripts/extract_sft_data.py`（SFT、未配線）・`apps/evaluator/scripts/extract_dpo_data.py`（DPO）。SFTは完成文（語り手ペルソナの文体込みの1本の文字列）ではなく `odai → toku + kokoro` の構造化データとして抽出し、文体の混入を原理的に防ぐ。DPOは同一お題内でのGemini/ELYZA比較（Tier A）とスコアバケットによる横断比較（Tier B）に、`user_feedbacks`由来ペアに限り**自己評価の除外**（語り手ペルソナ所有者が自作を評価したフィードバックを除外）と**寄与上限**（単一owner_uid・単一version_idいずれも全体の5%まで）を適用する。管理者キュレーション由来のペアは人間の審査ゲートを経ているため対象外。
  - **第2層（反応）**: `persona_reactions` コレクション（`nazokake_core/persona_reactions.py`）。「座布団」リアクションは`zabuton_count`への単純カウントアップから**1反応＝1レコードの追加（Insert-only）**へ移行し、旧カウントはそれ以前の蓄積分を表すbaselineとして凍結する。
  - **第3層（訂正）**: 「赤ペン」添削は歴史的に2系統（persona_main_function版の`corrections`コレクション／evaluator道場破りフィードのSQLite `origin_type="user_akapen"`行）に分かれており、`nazokake_core/correction_pairs.py`が読み取り時に統合する（書き込み口の一本化は未着手）。系統B由来のデータには訂正前後の`s_total`差分を付与する。
  - 管理コクピット（`GET /api/admin/dataset-layer-summary`）で3層それぞれの件数を確認できる。

## 7. 開発プロトコル（Guardrails）
- **推測の排除**: エラー発生時は必ずファクト（ログ、DBダンプ等）を取得し、仮説に基づくコード提供を禁ずる。
- **最小変更の原則 (MVF)**: 副作用（Side-effect）を事前評価し、ファイル全体の盲目的置換を避ける。
- **6手先の明示プロトコル**: 「情報収集 ➔ 設計・実装 ➔ 連携 ➔ 組み込み ➔ テスト ➔ 完了」のステップを事前に提示し、合意を得てから進める。

## 8. 変更履歴（検証ログ）
- 2026-07-26: `test/agent-benchmark` を `main` へ Force Push（無関係な履歴を上書き、instructions/221）。`deploy_cloud_run.yml` の `paths: apps/**` フィルタは force push 前後で共通祖先を持たないため発火せず、この1行差分コミットで初回のパイプライン検証を実施。
- 2026-08-13: persona_feature_plan_v3.md Phase9。§2「データベース」の記述（「Firestoreのみ、クライアント直接アクセス禁止」）が実装（Local-First SQLite SSoT + Firestoreバックアップレプリカ、掲示板のみ例外）と乖離していたため実装に合わせて修正。あわせてPhase1〜8で実装した語り手ペルソナのFirestore SSoT化・同期対象4テーブル追加・3層データセット基盤（構造/反応/訂正）を§2・§6へ反映。
