# 「幻のパイプライン」統合アーキテクチャ設計

- 作成日: 2026-07-12
- 対象: `tools/nazo_agent.py`, `tools/agent_graph.py`, `tools/ast_modifier.py`
- 目的: Epic 1(防弾化)・Epic 4(可観測性)で完成した「Claude Tool Calling + Pydantic +
  自己修正ループ + libcst AST置換」パイプラインが `main_flow` の本線から呼ばれていない
  問題(以下「幻のパイプライン問題」)を解消し、最も合理的で安全な統合方針を提示する。

## 1. 現状解析

### 1.1 `main_flow` の本線(現在ライブなパス)

`main_flow`(`tools/nazo_agent.py:1289`)は以下の順で実行される:

1. `phase0_ruff_autofix` — Ruffによるネイティブ自動修復(トイル除去)。
2. `_ensure_auto_audit_branch` — `TARGET_APP_DIR` 側に隔離ブランチ(`auto-audit-temp`)を切る。
3. `phase1_audit` — Ruff/mypyで `TARGET_APP_DIR/TARGET_CODE_DIR`(既定: `apps/evaluator/backend`)を静的解析し、`error_log.txt` を生成。
4. **`build_static_context` を呼ぶが、その結果を使うコード(旧Aiderフロー = `phase2_claude_translation`/`phase2_claude_tool_augmented`/`phase3_aider_execution` の呼び出し)は `main_flow:1320-1345` で丸ごとコメントアウトされている。**
5. 代わりに `acd_parse_error_locations` でエラーログ中の最初のファイル参照を1件だけ拾い、`tools.agent_graph.run_self_repair(str(resolved_target))` を呼ぶ(`main_flow:1364-1366`)。
6. `run_self_repair`(`tools/agent_graph.py`)は **Ollama(`gemma4:12b`)** を使ったLangGraphループ:
   `scanner → reviewer → (editor ⇄ tools[get_type_info]) → finalize_edit → scanner ...`
   を最大 `MAX_REVISIONS=3` 回まわし、`CLEAN` 判定が出るか回数上限に達したら `reporter` で
   ファイル全体を一括書き戻す。編集は **ファイル全文の自由記述リライト**(`editor_llm_node`)
   で、Markdownフェンス除去のみの素朴な後処理(`finalize_edit_node:135-140`)しか防御がない。
7. 修正が入れば `TARGET_APP_DIR` 側で `git add`/`git commit` し、SFT抽出フック
   (`tools/extract_agent_sft.py`)を叩く。

**要点**: 本線は「単一ファイル・全文書き換え・ローカルLLM・型情報ツールのみ」で動いており、
Pydanticスキーマ保証・Tool Calling強制・シンボル単位のAST置換・自己修正リトライ・
デッドレター記録のいずれも経由しない。

### 1.2 防弾化されたClaudeパイプライン(現在未接続)

- `phase2_claude_translation`(`tools/nazo_agent.py:622`): エラーログ+要件定義書から、
  Claude APIへ `submit_ast_modifications` ツールを `tool_choice` 強制で呼び出す。
  ツールの `input_schema` は `tools.ast_modifier.AstModificationInstruction.model_json_schema()`
  をそのまま流用(Single Source of Truth)。各タスクは `AstModificationInstruction(**t)` で
  Pydantic検証し、`ValidationError` 発生時は `tool_result(is_error=True)` でClaudeへ
  エラー内容を返し再生成させる自己修正ループ(最大3回、`MAX_SELF_CORRECTION_RETRIES`)。
  3回失敗すると `_write_dead_letter` が `tools/audit_reports/dead_letters/` へ
  タイムスタンプ・システムプロンプト・全会話履歴・最終エラー・生の応答を構造化JSONで
  保存し、縮退運転(タスク0件)で安全に継続する。
- `phase2_claude_tool_augmented`(`tools/nazo_agent.py:789`): 上記に加え
  `get_symbol_definition`/`read_file_section`/`get_type_info` の調査ツールをClaudeに
  公開し、自律調査後に `submit_aider_plan`(`AiderTask`: `file_path`+`instruction` のみ、
  `target_name`/`new_code` は持たない)で提出させる別系統。
- `phase3_aider_execution`(`tools/nazo_agent.py:1070`): タスクの `mode` フィールドで
  分岐する既存のハイブリッド・ルーター。`mode == "ast_replace"` なら
  `tools/ast_modifier.py` をサブプロセスとして起動し(アトミック書き込み・セマンティック
  差分検証・多段バリデーションゲート済みのlibcst置換)、それ以外(`mode == "aider"`/未指定)
  はAiderへ委譲する。**このルーターはまさに「Claude生成タスクをAST置換とAider編集に
  振り分ける」ために作られているが、`main_flow` から呼ばれないため到達不能。**

**要点**: `phase2_claude_translation` は `AstModificationInstruction` を直接生成するため
`mode: "ast_replace"` のタスクしか作らず、`phase3_aider_execution` を素通りしてそのまま
`tools/ast_modifier.py` へ渡せる形になっている。一方 `phase2_claude_tool_augmented` は
`AiderTask` しか作らないため、`ast_replace` 経路には現状繋がらない(スキーマが違う)。

### 1.3 両パイプラインの構造比較

| 項目 | 本線(LangGraph/Ollama) | 幻のパイプライン(Claude) |
|---|---|---|
| LLM | ローカルOllama(`gemma4:12b`)、無料・低速 | Claude API、有料・高精度 |
| 編集単位 | ファイル全文 | 関数/クラス単位(libcst AST) |
| 出力保証 | 自由記述+Markdownフェンス除去のみ | Tool Calling強制 + Pydantic検証 |
| 失敗時の挙動 | 3回まで同一ノードをループ、最終的に無条件で書き戻し | 3回まで自己修正、失敗時はデッドレター記録+安全スキップ(書き込みしない) |
| 対象ファイル選定 | エラーログの最初の1件のみ(暫定実装) | Claudeが複数ファイル分のタスクを一括生成可能 |
| 書き込み | ファイル全文 `write_text` | `_atomic_write_text`(tempfile+fsync+os.replace) |
| 可観測性 | `audit_history` のprint/戻り値のみ | dead letter JSON、triage_result.json |

## 2. 統合方針の選択肢

### 案A: LangGraphノードとしてClaudeツール群を移植する

`agent_graph.py` の `editor_llm_node`/`finalize_edit_node` を、Claudeの
`submit_ast_modifications` Tool Calling + `AstModificationInstruction` 検証 + 自己修正
ループに置き換える(または並列ノードとして追加する)。`AuditState` に
`target_name: str | None` を追加し、`scanner_node` の出力を「問題点の箇条書き」から
「修正対象シンボル名 + 問題点」の構造化形式に変更する必要がある。

**メリット**
- 既存のscan→review→edit→loopという実戦済みの制御フロー(隔離ブランチ、
  `revision_count`、`audit_history`)をそのまま再利用できる。
- 1つのグラフ・1つの実行モデルに統一され、利用者から見た呼び出し方が変わらない。
- 将来的に「editorノードのバックエンドをOllama/Claudeで切り替え可能」にする拡張が
  グラフ内の条件分岐だけで済む。

**デメリット**
- `scanner`/`reviewer` はOllama、`editor` はClaudeという**混在プロバイダ構成**になり、
  2つのAPIクライアント・2つの認証・2つの障害モードを1つのループ内で扱う複雑さが増す。
- 現在ファイル全文をそのまま状態(`current_code`)としてやり取りしているが、
  シンボル単位のAST置換に切り替えるには「どの関数が壊れているか」をscanner側で
  構造化して特定させる必要があり、`scanner_node`/`reviewer_node` のプロンプトと
  出力形式の再設計が避けられない(本セッションの成果の使い回しだけでは終わらない)。
- 無料だったOllamaループにClaude APIコストが混入し、コスト予測が複雑になる。

### 案B: `main_flow` のルーティング自体をClaudeベースに切り替える(CLI引数/環境変数で選択可能に)

`main_flow:1320-1345` でコメントアウトされている
`phase2_claude_translation`(または`phase2_claude_tool_augmented`)→`phase3_aider_execution`
の呼び出しを復元し、既存のコメント中に残っている
`USE_TOOL_AUGMENTED_PHASE2` と同じ思想の環境変数/CLI引数(例:
`NAZO_AGENT_ENGINE=claude` か `--engine claude`、既定値は現状維持の `langgraph`)で
LangGraphループとClaudeパイプラインを排他的に切り替える。

**メリット**
- コードはほぼ「既に書かれて動くことが本セッションのベンチマークで実証済み」
  (Ruff→Pyright→Claude Tool Calling→libcst置換、7秒・成功率100%)のため、
  復元と結線だけで済み実装リスクが最小。
- `agent_graph.py`(現在ライブで依存されている経路)を一切変更しないため、
  既存の自律修復ループへの回帰リスクがゼロ。
- `phase3_aider_execution` の `mode` ディスパッチが最初からこの用途のために
  作られており、`phase2_claude_translation` の出力(`mode: "ast_replace"`)を
  無改造でそのまま流し込める。

**デメリット**
- 2つの独立したパイプラインが並存し続け、長期的には「どちらが正か」の判断・
  メンテナンス負荷が二重化する(統合ではなく単なる選択可能化に留まる)。
- 対象ファイル選定戦略が異なる(LangGraph側はエラーログの先頭1件、Claude側は
  複数ファイルタスク一括生成)ため、切り替えた瞬間に挙動の一貫性がなくなる。
- `phase2_claude_tool_augmented` を使う場合は `AiderTask` スキーマ(`target_name`/
  `new_code` を持たない)のため `ast_replace` 経路に載らず、Aiderへの非決定的委譲が
  残る。`phase2_claude_translation` 側を選ぶ必要がある。

### 案C(推奨): 信頼度ゲート付きハイブリッド・エスカレーション

LangGraph/Ollamaループを既定の第一防衛線として維持しつつ、
`reviewer_node` が `MAX_REVISIONS` 回のループ後も `CLEAN` 判定に到達できなかった
「Ollamaが自己修復しきれなかったファイル」に限り、`phase2_claude_translation` の
Tool Calling + 自己修正パイプラインへ**エスカレーション**する第二防衛線として
接続する。

具体的には `main_flow` のLangGraph呼び出し後、`final_state["status"] != "CLEAN"` の
場合にのみ、当該ファイルのエラー内容を `phase2_claude_translation` へ渡し、
返ってきた `AstModificationInstruction` を `tools/ast_modifier.apply_modification` へ
直接(サブプロセスを介さずインプロセスで)適用する。失敗時は既存のデッドレター記録が
そのまま効く。

**メリット**
- 通常時のコストは変わらず0円(Ollamaのみ)。Claude APIは「ローカルLLMが手詰まりに
  なった難しいケース」にのみ課金され、コスト効率が良い。
- 本セッションで実証済みの防弾機構(Pydantic検証・自己修正・アトミック書き込み・
  デッドレター)を、それが最も効く場面(ローカルLLMの限界)にちょうど当てはめられる。
- `agent_graph.py` の既存ループにも `phase3_aider_execution` にも大きな改造が不要
  (両者とも「今の形のまま、もう一段呼び出しを追加する」だけで済む)。

**デメリット**
- 「2段階防衛」の分岐ロジック自体が新規実装であり、案Bよりはコード量が増える
  (ただし案Aより遥かに小さい)。
- LangGraph側の`CLEAN`判定がそもそも不正確だと、エスカレーションが発火しない
  (見逃す)リスクがある — `reviewer_node` の判定精度に依存する。

## 3. 結論と推奨

実装コスト・既存資産の再利用度・回帰リスクの観点から、**まず案Bで「幻のパイプライン」を
CLI/環境変数で選択可能な形に復元し**、動作実績(ベンチマーク・実運用)を積んだ後に
**案Cのエスカレーション統合へ段階的に発展させる**のが最も合理的である。案Aは
scanner/reviewer側の再設計コストが大きく、混在プロバイダの複雑さに対するリターンが
薄いため、現時点では推奨しない。
