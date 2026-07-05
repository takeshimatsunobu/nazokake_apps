# Nazo-Agent プロジェクト 技術的負債・改善ロードマップ

Phase 0〜6のディレクトリ再編・コスト管理・自己進化ループ・MCPサーバー化を通じた
全域監査で発見された、未解決の課題と改善余地をまとめる。今後の開発の羅針盤とする。

最終更新: Phase 6完了時点の監査結果に基づく。

---

## 🔴 最優先で対応すべき重大ギャップ

### 1. コスト計測システムが実際の生成/評価フローに一切接続されていない
`SystemCostLog`・`cost_calculator.py`・ダッシュボード・予算アラートまで一式構築したが、
`async_log_system_cost`と`calculate_server_cost_jpy`は、それ自体の定義とテストコード
以外からは一度も呼ばれていなかった(確認済み)。つまり:
- `system_costs`コレクションは実運用では空のまま
- ダッシュボードは常に¥0を表示する
- `is_budget_exceeded`は常に`False`を返し続け、予算アラートが実質機能していない

配管は完成しているが、蛇口が開いていない状態。`generate.py`の`process_gemini`/
`process_elyza`、`evaluation.py`の`run_evaluation`の各呼び出し完了時に
`async_log_system_cost`を呼ぶ配線が必要(Gemini APIレスポンスの`usage_metadata`
からトークン数を取得する)。

> **対応状況**: 本ドキュメントと同時に着手・修復。

### 2. 価格テーブルに実際使用中のモデルが欠落している
`generation.py`は`fallback_model = "gemini-3.5-flash"`を使用しているが、価格テーブル
(`PRICE_TABLE_USD_PER_M_TOKENS`)には`"gemini-2.5-flash"`・`"gemini-1.5-pro"`・
`"claude-3-5-sonnet"`しか登録されていなかった。上記1を修正しても、実際の生成コストは
「未知モデル=0円」として静かに計上漏れする。実運用モデル名と価格テーブルのキーを
一致させる棚卸しが必要。

> **対応状況**: 本ドキュメントと同時に着手・修復。

### 3. `admin.py`にエンドポイントが1つも存在しない
過去のマージ事故(`_resolve_statuses`の破損と同根)で、`ConfigUpdateRequest`・
`FeedbackInvalidateRequest`・`HumanActionRequest`はimportされているのに、それらを
使う`@router`エンドポイントが0件だった。これは連鎖的な影響がある:
- 管理者による「golden/approve/reject」キュレーションAPIが存在しない →
  `gemini_status`/`elyza_status`を書き換える手段がない
- Phase 4.11で実装したDPO抽出の「管理者キュレーションTier A/B」は、そもそも
  このステータスを設定するAPIがないため、恒久的に0件抽出になっている可能性が高い
- AIモデル設定(temperature/system_prompt)を更新する管理画面機能も動いていない

> **対応状況**: 本ドキュメントと同時に着手・復旧。

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

実害・データ損失リスクの観点から、以下の3点が最も緊急度が高いと判断する:

1. コスト計測の配線と価格テーブル修正(🔴 1, 2)
2. `admin.py`の復旧(🔴 3)
3. `apps/batch_factory`・`Nazokake_localLLM`のリモート設定(🟠)
