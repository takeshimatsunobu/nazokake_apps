# Nazo-Agent プロジェクト 技術的負債・改善ロードマップ

Phase 0〜6のディレクトリ再編・コスト管理・自己進化ループ・MCPサーバー化を通じた
全域監査で発見された、未解決の課題と改善余地をまとめる。今後の開発の羅針盤とする。

最終更新: nazo_agent.py の起動障害修正(ModuleNotFoundError / フロントエンド
非ブロッキング化)完了時点。

---

## ✅ 解決済み(旧🔴最優先)

### 1. コスト計測システムが実際の生成/評価フローに一切接続されていなかった
`SystemCostLog`・`cost_calculator.py`・ダッシュボード・予算アラートまで一式構築した
一方、`async_log_system_cost`と`calculate_server_cost_jpy`は、それ自体の定義と
テストコード以外からは一度も呼ばれていなかった(配管はあるが蛇口が閉まっていた状態)。

**対応済み**: `generate.py`の`generate_via_gemini`/`generate_via_llmjp`、
`evaluation.py`の`run_evaluation`の各呼び出し完了直後に`async_log_system_cost`を
配線。Gemini呼び出しは`response.usage_metadata`からトークン数を取得し、ローカル
(Ollama/ELYZA)は実行時間ベースで記録する。コストログ自体の失敗が生成/評価処理を
落とさないよう`try/except`で保護済み。フェイクFirestoreで`system_costs`への実書き込み
(0円ではない実額)を確認済み。

### 2. 価格テーブルに実際使用中のモデルが欠落していた
`generation.py`の`fallback_model = "gemini-3.5-flash"`が価格テーブルに未登録で、
上記1を修正しても「未知モデル=0円」として計上漏れする状態だった。

**対応済み**: `PRICE_TABLE_USD_PER_M_TOKENS`に`gemini-3.5-flash`を追加(暫定推定値、
実請求との照合が今後必要)。

### 3. `admin.py`にエンドポイントが1つも存在しなかった
過去のマージ事故(`_resolve_statuses`の破損と同根)で、`ConfigUpdateRequest`・
`FeedbackInvalidateRequest`・`HumanActionRequest`はimportされているのに、それらを
使う`@router`エンドポイントが0件だった。管理者キュレーション(`gemini_status`/
`elyza_status`の更新)手段が無く、Phase 4.11のDPO抽出Tier A/Bが恒久的に0件抽出に
なる連鎖的な影響があった。

**対応済み**: `HumanActionRequest`に欠落していた`model`/`action`フィールドを追加し、
`POST /api/admin/action`を実装。既存(orphanedだった)`_MODEL_STATUS_FIELD`/
`_ACTION_TO_STATUS`をそのまま活用。フェイクFirestoreで404・ステータス更新の
非干渉性(片方のモデルのみ更新されること)を確認済み。

### 4. `tools/nazo_agent.py` の起動障害
- `from tools.ast_mapper import ...`が`ModuleNotFoundError: No module named 'tools'`
  で失敗していた。`python tools/nazo_agent.py`のように直接実行すると`sys.path[0]`が
  `tools/`自身になり、リポジトリ直下パッケージとしての`tools`が解決できないため。
  **対応済み**: ファイル冒頭で`BASE_DIR`(リポジトリルート)を`sys.path`へ明示的に追加。
- フロントエンド(`dev_server.py`)の自動起動が、環境要因(Norton等のローカル
  セキュリティソフトが127.0.0.1へのHTTP接続をブロックしていると推測される。ポートは
  正しくLISTEN状態なのに接続が拒否される事象を確認)でタイムアウトし、最大30秒
  メインフロー全体をブロックしていた。フロントエンドはPhase1(監査)・Phase3
  (Aider自動修正)のどちらにも必須ではない。
  **対応済み**: `asyncio.create_task`によるfire-and-forget化。`startup_local_services()`
  はフロントエンドの起動結果を待たずに即座に戻り(実測0.01秒)、バックグラウンドタスクは
  例外を握りつぶして警告ログを出すのみで完了することを確認済み。

---

## 🟠 安定性(Stability)

- **`apps/batch_factory`と`Nazokake_localLLM`にリモートが設定されていない**
  (`apps/evaluator`にはGitHubリモートが設定済み)。ローカルディスク障害時、これら
  2リポジトリの全履歴・未コミット作業(LoRAチェックポイント含む)が完全に失われる。
  至急GitHub等へpushすることを強く推奨する。
- **`user_feedbacks`/`system_costs`コレクション用のFirestore複合インデックスが
  未定義**(`firestore.indexes.json`には`nazokake_fewshots`/`nazokake_items`用しか
  ない)。`admin_feedbacks.py`・`feedback_analyzer.py`・`extract_dpo_data.py`の
  クエリは`where`+`order_by`を異なるフィールドで組み合わせており、実データ規模で
  初めて`FAILED_PRECONDITION`エラーとして顕在化する。
- **Lv.1/Lv.2の自己進化状態が揮発性**。`_FEWSHOT_POOL`への高評価データのマージ、
  `_DYNAMIC_CORRECTION_PROMPT`はいずれもプロセス内メモリのみに存在し、サーバー
  再起動で消える。Cloud Run等では再起動が頻繁に起きるため、学習された改善が
  定着しない。Firestoreの設定ドキュメントに永続化し、起動時にロードする設計への
  発展を推奨する。
- **自動テスト・CIが存在しない**。今回の全検証はその場限りのフェイクFirestore
  スクリプトで行った。`evaluate_and_update_task`消失のような回帰を機械的に防ぐには、
  これらのテストパターンをpytestスイートとして`tests/`配下に残し、CIで回す仕組みが
  必要。
- **`train_model.py`の`../nazokake-evaluator/...`パスがPhase 0のディレクトリ再編で
  壊れたまま**(SFTパイプライン、DPOとは別系統のためスコープ外で報告のみ)。
- MCPサーバーの`trigger_dpo_pipeline`はタイムアウト時に直接の子プロセスは終了
  させるが、子プロセスがさらに生成した孫プロセスが残る可能性がある(軽微)。

---

## 🟡 なぞかけの質の向上

- **Tier B(cross_prompt)の構造的弱さ**: 無関係なお題同士を強制的にペアリングする
  ため、対比の質がTier A(同一プロンプト比較)より低い。Tier Aのデータ(同一
  `doc_id`内でGemini/ELYZA比較、または管理者キュレーションの両極比較)が十分に
  貯まった段階で、Tier Bの比率を徐々に下げる/打ち切る運用を推奨する。
- **静的Few-shotプール(`data/nazokake_fewshot.json`)に「劣化した例の自動除外」
  機構がない**。Lv.1は高評価データを追加する一方で、陳腐化・低評価が判明した
  既存の固定サンプルを取り除く仕組みがなく、プールが際限なく肥大化する。
- **評価者(Gemini)自体のドリフト検知手段がない**。Lv.2の過信検出はユーザー
  フィードバックとの乖離を見るが、絶対的な「ゴールドスタンダード」セット(既知の
  正解付きサンプル)による定期キャリブレーションがあれば、評価者そのものの劣化・
  偏りをより早期に検出できる。
- **LoRA学習にホールドアウト検証セットがない**(`train_dpo.py`/`train_model.py`
  とも訓練データ全件を学習に使用)。過学習を定量的に検知できないため、学習前に
  データの一部を検証用に分離する設計を推奨する。

---

## 🟢 コスト削減

- 価格テーブルの棚卸しと実配線を終えたうえで、予算超過時にログ警告だけでなく
  通知(Slack/メール)を送る、または段階的に「ローカルLLM優先ルーティングへの
  一時切り替え」のような能動的な制御を検討する余地がある(現状は意図的に
  ソフトリミットのみ)。
- サーバー電気代(`calculate_server_cost_jpy`)も未配線のため、Ollama稼働コストは
  可視化されていなかった。ローカル実行の実行時間計測・記録を`generate_via_llmjp`
  にも追加すると、「クラウドAPI vs 自前サーバー」の本当のコスト比較ができるように
  なる。

---

## 優先度サマリー

🔴だった重大ギャップ(コスト計測の配線・価格テーブル・`admin.py`復旧・
`nazo_agent.py`の起動障害)はすべて対応済み。残る課題のうち、実害・データ損失
リスクの観点から以下が最も緊急度が高いと判断する:

1. `apps/batch_factory`・`Nazokake_localLLM`のリモート設定(🟠、ディスク障害で
   全履歴・未コミット作業が失われるリスク)
2. `user_feedbacks`/`system_costs`用のFirestore複合インデックス定義(🟠)
3. Lv.1/Lv.2自己進化状態の永続化(🟠、サーバー再起動で学習成果が消える)
