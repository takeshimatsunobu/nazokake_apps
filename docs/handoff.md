# 引き継ぎメモ（docs/handoff.md）

> 作成日: 2026-08-12。作成時点のHEADコミット: `42a2297`（apps/evaluator, apps/persona_main_function,
> packages/shared_core側）。`apps/batch_factory`は独立gitリポジトリのため別途記載（§6）。
> プロジェクト概要・技術スタック・設計判断は [`CLAUDE.md`](../CLAUDE.md) を参照。
> このファイルは「今どうなっているか」「次に何をすべきか」に特化する。

## 1. 現在の実装状況

### 完了済み
- **apps/evaluator**: DDD構成のFastAPIバックエンド（ルーター14分割）、MVC分離済み
  フロントエンド（Vanilla JS）、Gemini+ELYZAのデュアル生成パイプライン、11軸評価、
  5ペイン管理コクピット（招待制認証・DLQ管理・直談判レビュー・コスト管理・ペルソナ設定、
  コミット`f56776a`）、ユーザー評価×Few-shotの5段階フィードバックループ
  （`golden`/`good`/`hmm`/`tolerable`/`troll`、コミット`846cbe5`）。
- **apps/persona_main_function → 2026-08-16、apps/evaluator/backendへ統合済み（案B）**:
  Step1属性推定＋Step2生成の2段パイプライン、Route A/B分岐、few-shot注入、
  Firestoreキャッシュ、荒らし対策の段階的ブロック、マイペルソナCRUD・Geminiドラフト
  自動生成・並替・削除機能一式を`apps/evaluator/backend`へ統合し、単一のCloud Run
  サービスとして稼働する構成へ変更した（詳細は`docs/persona_feature_plan_v3.md`§12.3）。
  `apps/persona_main_function`ディレクトリはフロントエンド（`frontend/`）とFirebase
  Hosting設定のみが残る。バックエンドテストは`apps/evaluator/backend/
  test_persona_generate_resolution.py`（6件）へ移設済み。依然として大部分（Route A/B
  分岐・few-shot注入・段階的ブロック・マイペルソナCRUD本体）はテスト未整備
  （後述、§2課題B）。
- **packages/shared_core**: SQLite SSoT + Firestore同期の基盤、Alembicマイグレーション
  11本、few-shotプール、persona定義SSoT、品質サーキットブレーカーが整備済み。
- **CI/CD**: PRゲート（Dockerビルド+脆弱性スキャン、pytest、Pyrightラチェット型検査）、
  mainマージ時の自動デプロイ（Cloud Run + Firebase Hosting）が稼働中。
- **ELYZAレイテンシ最適化**: httpx.AsyncClientのブロート解消（22.8秒→7.3秒）、
  best-of-3からbest-of-1への変更、VRAMロック関連のリエントラント化・クールダウン短縮
  （2.0秒→0.5秒）、ワーカーpolling間隔短縮（8.0秒→2.0秒）。直近コミット`42a2297`まで
  一連の高速化・堅牢化作業が続いている。

### 実装中・未確定
- **ELYZA→Gemini「代打」フォールバック**: `_wait_for_elyza_worker_or_none()`の
  タイムアウトを65秒→32秒に短縮したばかり（コミット`42a2297`）。ローカルGPUワーカーが
  §2で述べる理由で頻繁にdead_letter化している状況下で、このタイムアウト値が適切かは
  実運用で未検証と見られる。
- **`evaluation.py`内の未実装スタブ**: `apps/evaluator/backend/services/evaluation.py:206,211`
  に`# TODO: Fetch/Save from actual DB setting table`とあり、ある設定値がDB永続化されず
  空文字を返す実装のまま残っている（具体的にどの設定かは当該関数名を確認のこと、
  **未確認**: ユーザー影響の有無）。
- **`packages/shared_core/nazokake_core/models.py`のTriggerStateORM重複疑い**:
  `database.py`側にも同名の`TriggerStateORM`が別の宣言的ベースで定義されており、
  どちらが実際に使われているか、あるいは片方がデッドコードかが**未確認**。

### 未着手・要判断
- **GCP VM時代の残骸スクリプトの削除**: `apps/evaluator/deploy_production.ps1`,
  `deploy_image.ps1`, `scripts/wake_up_vm.py`, `scripts/start_fortress.ps1`,
  `scripts/scan_regions.ps1`, `scripts/setup_gcp_l4_instance.py`,
  `scripts/find_norton_ca.ps1`, `scripts/hunter_gcp_instance.ps1` の8ファイルに
  `# TODO: 2026-08-11を以て、このファイルは完全に削除すること (Sunset Date)`という
  同一のTODOコメントが付いている。**サンセット日は昨日（2026-08-11）を過ぎている**が
  未削除。`deploy_production.ps1`は実行すると即`exit 1`するtombstone状態。
- **apps/batch_factoryのrequirements.txt破損**: 10〜13行目にgrep出力らしきゴミ文字列
  （`C:\Users\takes\nazokakebatchfactory\requirements_temp.txt:13:chromadb==1.5.9`）が
  そのままファイル内容として混入しており、有効な依存リストとして機能しない状態。
- **`run/ssot_audit_report.md`の信頼性**: 36,958行あるが、実体調査の結果
  「Undocumented」「Canonical Naming Map」セクションの大半は`.venv`内のサードパーティ
  パッケージ（Pillow, onnxruntime, cryptographyのベンダー同梱物）を誤って自プロジェクト
  コードとして拾ったノイズと判明。監査ツール自体に`.venv`除外の修正が必要（未着手）。
- **APIキーが平文で入った`.env.example`**: `apps/evaluator/backend/.env.example`に
  プレースホルダーではなく実際のAPIキー形式の値（GEMINI_API_KEY, ANTHROPIC_API_KEY,
  HF_TOKEN）がそのまま書かれている状態を発見した（git追跡はされていないため外部流出は
  していない）。ダミー値へ差し替えるか、該当キーのローテーションを検討すべき。

## 2. いま詰まっている点・未解決の課題（再現手順つき）

### 課題A: ローカルELYZAワーカーが繰り返しクラッシュ・再起動している（進行中の可能性）

**症状**: `run/audit_reports/start_elyza_worker.log`（直近更新: 本日、コミット`42a2297`と
ほぼ同時刻帯）に、以下2種類の失敗パターンが2026-08-12 03:52〜04:01の間に繰り返し記録
されている。

1. **Gemini APIへのネットワーク到達性エラー**（gRPC/HTTPS接続がタイムアウト）:
   ```
   google.api_core.exceptions.RetryError: Timeout of 300.0s exceeded, last exception:
   503 failed to connect to all addresses; last error: UNAVAILABLE:
   ipv4:172.217.211.95:443: WSAGetOverlappedResult: Connection timed out
   ```
   このエラーの直後にワーカープロセス自体が`exit=-1`で異常終了し、15秒後に自動再起動
   している。

2. **VRAMロック取得失敗の連鎖**（上記1の後、複数ジョブが立て続けに失敗）:
   ```
   RuntimeError: VRAMロックを取得できませんでした
   （他プロセスがVRAMを使用中のため、ELYZA生成を諦めました）。
     at apps/evaluator/backend/services/generation.py:638
     raised from workers/ondemand_elyza_worker.py:284
   ```
   このエラーになったジョブは即座に`dead_letter`へ落とされる（コミット`42a2297`で
   リトライキュー方式を廃止したため）。

**再現手順**:
1. `scripts\start_elyza_worker.ps1`（または`start_dev.ps1`経由）でワーカーを起動する。
2. `run/audit_reports/start_elyza_worker.log`を`tail -f`相当で監視する。
3. なぞかけ生成をevaluatorのUIまたはpersona_main_function経由で複数連続実行する。

**未確認/要調査**:
- ネットワークエラー（1）が、ユーザーメモリにある「NortonによるTLS中間者検査が
  gcloud IAP SSHで問題を起こした」事例（別コンテキスト）と同種のローカルネットワーク
  要因なのか、それとも単純な一時的な回線断なのかは未確認。直近コミット`42a2297`の
  コミットメッセージ内でも「ローカル環境がTLS中間者検査(Norton)の影響でuv lockの
  ネットワーク解決を実行できなかった」という記述があり、同種の環境要因が疑われる。
- VRAMロック失敗（2）が、（1）のプロセスクラッシュ→再起動サイクルの中でロックが
  正しく解放されずに残留した結果なのか、それとも単純に複数ジョブが同時に来て
  正常に排他制御が働いている（想定内の挙動）だけなのかは、ログの前後関係だけでは
  断定できない。`generation.py`のVRAMロック取得・解放ロジック（特にプロセス異常終了時の
  ロックファイルのクリーンアップ有無）を読む必要がある。
- ログは04:01:46「起動します」で切れており、その後正常化したのか、クラッシュが
  継続しているのかは**このログだけでは不明**（監視を続けるか、直近の実行状況を
  ユーザーに確認する必要がある）。

### 課題B: apps/persona_main_functionのテストが依然として大部分未整備（2026-08-15一部更新）
2026-08-15に`test_generate_persona_resolution.py`（ペルソナ解決・プロンプト合成ロジックの
単体テスト6件、`cd apps/persona_main_function && pytest test_generate_persona_resolution.py`
で実行）を追加したが、これはPhase5「生成パスへの記録」まわりのみ。Route A/B分岐・
few-shot注入・段階的ブロック・マイペルソナCRUD API（作成/更新/削除/並替/引き継ぎコード）
本体には引き続きテストが無い。`docs/persona_feature_plan_v3.md`§11に定義された
テスト一覧（認可・上限・不変性・移行・記録・ドラフト・学習・引き継ぎ・論理削除）は
未着手のまま。

### 課題D（2026-08-15発見 → 2026-08-16対応完了）: workers/ondemand_elyza_worker.pyがnarrator_persona_id等を記録しない
根本原因は、Cloud Run側`generate_ai()`が書き込む先（一時SQLite、`/tmp`）とELYZA
ワーカーが動くローカルマシンの`nazokake_local.db`が別ファイルであるため、ワーカーが
新規行として挿入する際に4列がserver_default（`"No_Data"`/`"no_data"`）のまま
記録され続けていたこと。`_resolve_narrator_persona_fields()`を新設し、ワーカー
自身のローカルSQLite書き込み時に独自解決するよう対応済み（詳細は
`docs/persona_feature_plan_v3.md`§12.2）。単体テスト`workers/test_narrator_persona_fields.py`
（8件）で検証済み。

### 課題C: ドキュメント（PROJECT_CORE.md）と実装のDB構成の乖離
`apps/evaluator/PROJECT_CORE.md`は「データベース: Firestore」とだけ記載しているが、
実装は「SQLiteがSSoT、Firestoreは非同期バックアップ」という構成になっている
（`packages/shared_core/nazokake_core/database.py`, `firestore_sync.py`のコメントで
明記）。ドキュメントの更新が追いついていない可能性が高い。新しくこのプロジェクトに
入るエージェント/開発者がPROJECT_CORE.mdだけを読んで実装判断をすると誤る恐れがある。

## 3. 直近のエラーログ（該当箇所抜粋）

`run/audit_reports/start_elyza_worker.log` より、最も新しいクラッシュ発生箇所の
スタックトレース全文（個人情報・秘密情報は含まれていないことを確認済み）:

```
google.api_core.exceptions.RetryError: Timeout of 300.0s exceeded, last exception: 503 failed to connect to all addresses; last error: UNAVAILABLE: ipv4:172.217.211.95:443: WSAGetOverlappedResult: Connection timed out (A connection attempt failed because the connected party did not properly respond after a period of time, or established connection failed because connected host has failed to respond.

 -- 10060)
[start_elyza_worker] 2026-08-12 03:52:29 ワーカーが異常終了しました(exit=-1)。15秒後に自動再起動します。
[start_elyza_worker] 2026-08-12 03:52:44 起動します。
[ondemand_elyza_worker] デーモンとして起動しました(ポーリング間隔: 2.0秒)。
[ondemand_elyza_worker] 🎯 [764ab0a1fe22419ea0a491d7f5573e2c] ジョブをclaimしました(odai='傘')。
⏳ [VRAM保護] Ollamaの計算リソースをロックしました。VRAM解放のため0.5秒間クールダウンします...
🏠 [1発入魂] ローカル ELYZA で生成中... (http://localhost:11434/v1/chat/completions, model=elyza:8b)
✅ ELYZA生成に成功！VRAMロックを解除します。
[ondemand_elyza_worker] ✅ [764ab0a1fe22419ea0a491d7f5573e2c] ELYZA生成・評価・Firestore書き戻しが完了しました。
[ondemand_elyza_worker] 1件処理しました。
[ondemand_elyza_worker] 🎯 [e70634392708449b9ba56b2a89bd44cd] ジョブをclaimしました(odai='信号機')。
[ondemand_elyza_worker] ⚠️ [e70634392708449b9ba56b2a89bd44cd] ELYZA生成に失敗したため、即時failedとして書き戻します: VRAMロックを取得できませんでした(他プロセスがVRAMを使用中のため、ELYZA生成を諦めました)。
Traceback (most recent call last):
  File "C:\Users\takes\nazokake_apps\workers\ondemand_elyza_worker.py", line 284, in _process_job
    raw_result = await generate_via_llmjp(odai, persona_prompt, temperature)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\takes\nazokake_apps\apps\evaluator\backend\services\generation.py", line 638, in generate_via_llmjp
    raise RuntimeError(
    ...<2 lines>...
    )
RuntimeError: VRAMロックを取得できませんでした(他プロセスがVRAMを使用中のため、ELYZA生成を諦めました)。
[ondemand_elyza_worker] 📮 [e70634392708449b9ba56b2a89bd44cd] ELYZA生成に失敗したため即時dead_letterとしました: VRAMロックを取得できませんでした(他プロセスがVRAMを使用中のため、ELYZA生成を諦めました)。
[ondemand_elyza_worker] 1件処理しました。
（同種のVRAMロック失敗が odai='図書館', odai='温泉' でも連続発生 — 中略）
[start_elyza_worker] 2026-08-12 03:58:22 ワーカーが異常終了しました(exit=-1)。15秒後に自動再起動します。
[start_elyza_worker] 2026-08-12 03:58:37 起動します。
[ondemand_elyza_worker] デーモンとして起動しました(ポーリング間隔: 2.0秒)。
[start_elyza_worker] 2026-08-12 03:59:59 ワーカーが異常終了しました(exit=-1)。15秒後に自動再起動します。
[start_elyza_worker] 2026-08-12 04:00:14 起動します。
[ondemand_elyza_worker] デーモンとして起動しました(ポーリング間隔: 2.0秒)。
[start_elyza_worker] 2026-08-12 04:01:31 ワーカーが異常終了しました(exit=-1)。15秒後に自動再起動します。
[start_elyza_worker] 2026-08-12 04:01:46 起動します。
[ondemand_elyza_worker] デーモンとして起動しました(ポーリング間隔: 2.0秒)。
```

その他のログファイルは基本的に正常出力のみ（`apps/batch_factory/err.log`,
`apps/batch_factory/out.log`は6月12日付で古く直近の問題とは無関係。
`run/audit_reports/nazo_agent_daemon.log`は正常なruff autofix出力のみ）。ただし
`run/audit_reports/service_backend.log`に1行だけ以下のエラーがある（発生日時: 8月2日、
古い可能性あり）:
```
[nazo_agent] Backend (FastAPI) 自動起動エラー: [WinError 2] 指定されたファイルが見つかりません。
```

## 4. 次にやろうとしていたこと／検討中で未決定の選択肢

- 直近のコミット`42a2297`のコミットメッセージから、この一連の変更（best-of-1化、
  VRAMクールダウン短縮、代打タイムアウト短縮）は「ELYZA爆速化」を目的とした一連の
  最適化の一環と読み取れる。次の一手としては、§2課題Aのネットワークエラー・VRAM
  ロック連鎖が最適化後も解消していないかの実運用確認が優先度高いと考えられる
  （**これは私の推測であり、ユーザー本人に次の優先事項を確認するのが望ましい**）。
- `evaluation.py`のDB設定未実装スタブ（§1）をいつ実装するかは未定。
- `apps/batch_factory`を正式なgit submoduleにするか、あるいは別の統合方法
  （monorepoへの一本化等）にするかは検討の余地がある構成上の課題（未確認: 意図的に
  現状維持を選んでいる可能性もある）。
- GCP VM時代の残骸スクリプト8ファイル（§1参照）は、サンセット日を過ぎているため
  次のクリーンアップ機会で削除するのが自然だが、まだ実行されていない。

## 5. 「このファイルを見せれば話が早い」重要ファイル（優先度順）

1. `packages/shared_core/nazokake_core/database.py` — DB設計（SQLite SSoT）の一次情報。
   ドキュメントより実装を信じるべき理由がここにある。
2. `apps/evaluator/backend/services/generation.py` — Gemini/ELYZAデュアル生成の中核。
   VRAM排他制御・「1発入魂」ロジック・§2課題Aのエラー発生源（638行目）。
3. `workers/ondemand_elyza_worker.py` — ローカルGPUワーカー本体。§2課題Aの直接の
   呼び出し元（284行目）。
4. `run/audit_reports/start_elyza_worker.log` — 現在進行中と思われる不具合の一次証拠。
5. `apps/evaluator/PROJECT_CORE.md` — プロジェクトの「生きたドキュメント」。ただし
   §2課題Cの通り一部実装と乖離している点に注意して読むこと。
6. `packages/shared_core/alembic/versions/f7a2c9e5b1d4_add_llmjp_pinch_hitter_fields.py`
   （マイグレーションのchain head）— 直近のスキーマ変更内容を知る最短経路。
7. `apps/persona_main_function/services/step2_generation.py` — 最も新しく追加されたサービスの
   中核ロジック。テスト不在（§2課題B）の対象でもある。
8. `run_api.ps1` / `start_dev.ps1` — 開発環境の起動方法と、そこに埋め込まれた過去の
   トラブル対応（引用符エスケープ問題、BOM無しUTF-8パースエラー等）の記録。
9. `.github/workflows/pyright_check.yml` — CIの実際のテスト・型検査コマンドが
   コメント込みで一番詳しく書かれているファイル（`instructions/266`等の背景説明あり）。
10. `CLAUDE.md`（このファイルの隣） — 本ドキュメントとあわせて読む前提の全体像。

## 6. apps/batch_factory（独立gitリポジトリ）についての補足

`apps/batch_factory`はルートリポジトリとは別の`.git`を持つ独立リポジトリで、
ルートからは`.gitmodules`なしの「埋め込みリポジトリ」参照として存在する
（詳細は`CLAUDE.md`§5末尾）。そのため:
- ルートで`git status`しても`modified: apps/batch_factory (modified content, untracked content)`
  としか出ない。中身を見るには`git -C apps/batch_factory status`を使う必要がある。
- 現在の`apps/batch_factory`側のuncommitted変更は、調査時点で**42件**あるが、
  その大半は`__pycache__/*.pyc`の差分（ビルド成果物のノイズ）で、実質的なソース変更は
  `batch/__init__.py`, `batch/firestore_sync_worker.py`の変更、および
  `batch/persona.py`, `batch/schemas.py.random_bak`の削除のみ。
- `apps/batch_factory/README.md`はこの削除を反映しておらず（`persona.py`,
  `schemas.py`をディレクトリ構成に含めたまま）、ドキュメントが現在の作業ツリーより
  古い状態。
- `batch/`パッケージ（現行の本番バッチパイプライン）と、直下にある
  `phase1_seed.py`/`phase2_generate.py`/`phase3_evaluate.py`（旧世代の並行実験、
  存在しないはずの旧ディレクトリ名`C:\Users\takes\nazokake-evaluator`をハードコード
  している）は**別物のパイプライン**である点に注意。後者はモノレポ以前の名残で、
  `train_model.py`のコメント内でも「現在は存在しない」と明記されている
  （ただし本機上には物理的に存在することが確認できた＝ローカル環境依存の可能性）。
