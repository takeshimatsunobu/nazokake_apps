# 実装計画書 v3（確定版）：語り手ペルソナのデータ化と「マイペルソナ作成ツール」

対象リポジトリ: `C:\Users\takes\nazokake_apps`
基準コミット: `33ab466`
作成日: 2026-08-12
v1 / v2 を置き換える確定版。以降はアジャイルにフェーズ単位で実装する。

---

## 0. 用語（本計画で厳守）

調査の結果、ペルソナ概念は**2つのみ**であることが確定した。第3の概念は存在しない。

| 呼称 | 実体 | 本計画での扱い |
|---|---|---|
| **narrator persona** | `PERSONAS[1..10]`（`name` + `prompt`） | **本機能の対象**。DB化しユーザーが追加できるようにする |
| audience persona | Big5性格特性＋職業13分類 | **全廃**（§2） |

### 紛らわしい命名の是正

`apps/persona_router` は `main.py:4` および `models/schemas.py:4` で自らを
**「ペルソナ推定とルーティングシステム」**と名乗っているが、Step1が推定しているのは
**お題の言語的性質7属性**であり、ペルソナでもユーザー属性でもない。

→ docstring を「**お題属性推定とルーティングシステム**」に修正する。
実装は一切変更しない（Step1は生成パイプラインの中核）。

### 命名規約

| 対象 | 名前 |
|---|---|
| Firestore コレクション | `narrator_personas` / `narrator_persona_versions` |
| `nazokake_items` 新規列 | `narrator_persona_id` / `narrator_persona_version_id` / `narrator_persona_name` |
| shared_core 新規モジュール | `narrator_personas.py` |
| API パラメータ | `narrator_persona_id`（既存 `persona_id` は当面エイリアスとして受理） |

---

## 1. 確定した事実（設計の土台）

### 1.1 評価エンジン
- 現在の軸は **13個**（docstring は「11軸」のまま未更新）
- `s_total` = 全軸の**単純平均 × 5.0**（重みなし）
- 評価プロンプトへの入力は `odai` と構造合成文のみ。**ペルソナ情報は渡っていない**
- → 2軸削除後は **11軸**となり、docstring と一致する（§4）

### 1.2 Step1 推定（削除しない・変更しない）
`step1_estimation.py` が推定するのは**お題のみに依存する7属性**:
`is_valid_input` / `domain_category` / `vocabulary_difficulty` / `slang_level` /
`wordplay_flexibility` / `topic_scale` / `is_seasonal`

Route A/B 分岐の根拠は `is_valid_input` の1つのみ。ユーザー属性の推定処理は
リポジトリ全体に存在しない。

### 1.3 学習パイプライン（3経路）

| 経路 | 抽出元 | 判定根拠 | 自動配線 |
|---|---|---|---|
| DPO | `apps/evaluator/scripts/extract_dpo_data.py`（Firestore直読み） | 管理者キュレーション状態 ＋ `user_feedbacks.overall_score` | ✅ `tools/run_dpo_pipeline.py` |
| SFT(A) | `tools/extract_training_data.py`（SQLite） | `s_total >= 4.0` | ✅ Makefile |
| SFT(B) | `apps/evaluator/backend/scripts/extract_sft_data.py`（Firestore） | `training_filter`（実質no-op） | ❌ 未配線 |

いずれも persona 情報を参照していない（参照ゼロを grep で確認済み）。

### 1.4 インフラ
- Cloud Run は evaluator / persona_router とも **max-instances=20** → SQLite は共有不可
- `firestore_sync.py` の同期対象は **`nazokake_items` のみ**
- `firestore.rules` は全コレクション deny-all。全アクセスは Admin SDK 経由（ルールを迂回）
- 結果格納先が2系統: `nazokake_items`（evaluator）/ `nazokake_results`（persona_router）
- Firebase 匿名認証は実装済み（`ui/auth.js`）だが利用は掲示板投稿のみ

---

## 2. audience persona（Big5＋職業分類）の全廃

### 2.1 削除して安全である根拠

| 確認先 | 結果 |
|---|---|
| 生成プロンプト構築（`llm_client.py` の3関数） | `persona_prompt` のみ参照。`big5` / `occupation_*` は**参照ゼロ** |
| 学習抽出3スクリプト | 参照ゼロ |
| フロントエンド | 参照ゼロ |
| 管理コクピット・フィード | 参照ゼロ |
| `firestore_sync.py` | JSON列として素通しするのみ |

**書き込まれるだけで誰も読まないフィールド**である。
`master_personas.py` の docstring 自身が「本番マスターペルソナには Big5 の概念自体が
存在しない」と自認し、全フィールド `"n/a"` のプレースホルダを詰めている。

### 2.2 削除対象

| 対象 | ファイル |
|---|---|
| `Big5` / `PersonaMeta` の `big5` 必須制約 | `packages/shared_core/nazokake_core/schemas.py:55-67` |
| `MASTER_PERSONA_BIG5_PLACEHOLDER` | `apps/batch_factory/batch/master_personas.py` |
| `_to_persona_meta()`（バグの震源） | 同上:52-58 |
| ダミーBig5構築コード | `import_csv.py` / `import_offline_json.py` / `manual_dpo_importer.py` |

### 2.3 117件の救出 ← 削除前に必ず実施

混入の原因は `_to_persona_meta()` の以下の1行:

```python
occupation_name = entry["name"]   # 語り手ペルソナの表示名をそのまま代入
```

職業名フィールドに語り手ペルソナ名を書き込んでいた。**この関数自体が §2.2 で消える**ため
バグごと解消するが、**消す前に 117件を `narrator_persona_id` へ救出する**。

`occupation_name` が `PERSONAS[1..10]` の `name` と完全一致する行を機械判定できる。

`occupation_name` の全内訳（5148件）:

| 値 | 件数 | 扱い |
|---|---|---|
| 職業分類13種 | 4054 | 破棄 |
| `WebGemini (Offline)` | 938 | 破棄（生成経路名であり職業ではない） |
| **語り手ペルソナ名10種** | **117** | **救出 → `narrator_persona_id`** |
| `WebGemini (Manual)` | 39 | 破棄。**現行コードにも batch_factory の全git履歴にも存在しない値**（起源未確認） |

### 2.4 `persona` 列そのものの扱い

**物理列は残し、書き込みを停止する。**

- 読み取り側のコードが存在しないため、残しても実害がない
- Firestore 側にも同名フィールドがあり、両方の削除は高リスク
- 監査可能性（過去に何が入っていたか）を残せる
- ORM の docstring に「**廃止済み。書き込み禁止**」と明記する

---

## 3. 語り手ペルソナのデータモデル

### 3.1 Firestore を SSoT とする

Cloud Run の SQLite は `/tmp` かつ max-instances=20 のため、ユーザー生成データを
置けない。`board.py` と同じ「明示的な Firestore 例外」として扱う。

**`narrator_personas/{persona_id}`**

| フィールド | 型 | 説明 |
|---|---|---|
| `persona_id` | string | UUID。組み込みは `"1"`〜`"10"`、センチネルは `"No_Data"` |
| `owner_uid` | string | Firebase 匿名認証 UID。組み込みは `"SYSTEM"` |
| `owner_display_name` | string \| null | 赤ペン等で名乗った際に追記。**認可には使わない** |
| `display_name` | string | ペルソナ自身の名前 |
| `base_persona_id` | string \| null | 派生元 |
| `is_builtin` | bool | |
| `is_deletable` | bool | **削除ブロックの実体**。組み込みは `false` |
| `is_visible` | bool | センチネルを一覧から隠す |
| `current_version_id` | string | |
| `sort_order` | int | |
| `created_at` / `updated_at` / `deleted_at` | timestamp | 削除は論理削除 |

**`narrator_persona_versions/{version_id}`（追記専用）**

| フィールド | 型 |
|---|---|
| `version_id` | string（§3.3 参照） |
| `persona_id` | string |
| `version_no` | int |
| `settings` | map |
| `content_hash` | string |
| `created_at` | timestamp |

### 3.2 設定項目スキーマ

現在の `PERSONAS` は `name` / `prompt` の2キーのみ。以下に拡張する。

| キー | 型 | 適用先 | ツールチップ |
|---|---|---|---|
| `display_name` | str | — | このペルソナの呼び名です |
| `prompt` | str | 両経路 | AIに「あなたは誰か」を教える文章。人格の核になります |
| `first_person` | str | 両経路 | 一人称（僕・私・わし など） |
| `speech_style` | str | 両経路 | 語尾や口調の癖 |
| `tone` | enum | 両経路 | 全体の雰囲気 |
| `favorite_topics` | list[str] | 両経路 | 得意なお題のジャンル |
| `taboo` | list[str] | 両経路 | 触れさせたくない話題 |
| `thinking_level` | enum(low/medium/high) | **Gemini のみ** | AIがどれくらいじっくり考えるか |
| `temperature` | float 0.0–1.5 | **ELYZA のみ** | 発想の飛躍度 |

UI では両者を**1つの「じっくり度／飛躍度」スライダー**として見せ、内部で経路ごとに
振り分ける（Gemini は `temperature` を無視するため）。

### 3.3 不変性の担保 — 内容ハッシュをIDにする

Firestore にトリガーは無く、セキュリティルールも Admin SDK には効かない。
そこで**ID設計そのものに不変性を埋め込む**。

```python
version_id = f"{persona_id}__{sha256(canonical_json(settings))[:16]}"
```

内容が変われば **ID が変わる**ため、既存バージョンの上書きが原理的に起こらない。
同一内容の再保存は同一IDへの冪等な書き込みとなり、no-op 判定も自動で成立する。

**書き込み口は `narrator_personas.py` の2関数のみとし、バージョン更新関数は定義しない。**

- `create_persona(owner_uid, settings) -> (persona_id, version_id)`
- `save_persona_settings(persona_id, settings) -> version_id`

### 3.4 生成時のバージョン固定（レース対策）

ELYZA 生成は Firestore ジョブキュー経由の非同期処理。投入から実行までの間に
ユーザーがペルソナを編集し得る。

**ジョブペイロードに `narrator_persona_version_id` と、生成に使うプロンプト本文の
スナップショットを両方入れる。ワーカーは Firestore を引き直さない。**

### 3.5 `nazokake_items` への列追加（SQLite）

| 列 | デフォルト |
|---|---|
| `narrator_persona_id` | `server_default="No_Data"`, NOT NULL |
| `narrator_persona_version_id` | `server_default="No_Data"`, NOT NULL |
| `narrator_persona_name` | `server_default="No_Data"`, NOT NULL |
| `data_origin` | `server_default="no_data"`（`builtin`/`custom`/`no_data`） |

Firestore を SSoT にしたため **FK制約は張らず論理参照**とする。

移行時の埋め方:
1. `persona` JSON が `{persona_id, temperature}` 形（**10件**）→ その `persona_id` を採用
2. `occupation_name` が `PERSONAS` の `name` と完全一致（**117件**）→ 該当IDへ救出
3. それ以外（約5350件）→ `"No_Data"`

---

## 4. 評価軸の削減（13軸 → 11軸）

### 4.1 削除対象

| 軸 | 削除理由 |
|---|---|
| `S_persona` | 評価器にペルソナ情報が渡っていないため、**比較対象を知らないまま採点している**（機能不全） |
| `S_aufheben` | なぞかけで発動する場面が稀 |

### 4.2 実装

1. `evaluation.py` の `AXES` / `_AXIS_DESC` / `EVAL_SCHEMA` から2軸を削除
2. `schemas.py` の `Scores` から2フィールドを削除
3. 既存全件（約5480件）の `scores` JSON から2キーを削除
4. `s_total` を残り11軸の平均 × 5.0 で**再計算**

```python
for item in items:
    scores = json.loads(item.scores)
    scores.pop("S_persona", None)
    scores.pop("S_aufheben", None)
    item.scores = json.dumps(scores)
    item.s_total = round(sum(scores.values()) / len(scores) * 5.0, 4)
```

**復元手段は設けない**（決定事項）。

5. `evaluation.py` の docstring「11軸評価エンジン」は**そのままで正しくなる**

### 4.3 副作用の監視

`quality_circuit_breaker` は「10件中8件が極端値（`s_total >= 5.0` または `<= 0.0`）」で
トリップする。軸が13→11に減ると満点が揃う確率が上がるため、**切り替え前後で発火率を
継続監視する**（決定事項）。

### 4.4 `s_structure` は作らない

評価軸と評価要領を変更しないという決定により、構造軸のみの部分平均は導入しない。
**学習データ抽出の閾値判定は従来通り `s_total` を使う**（ただし値は11軸ベースに変わる）。

ガード1(a) は「2軸削除により表現軸の影響が減った `s_total` をそのまま使う」形に簡素化される。

---

## 5. 学習ループのガード

**方針**: ソースで排除せず、**レイヤーで分ける**。カスタムペルソナ由来のデータも
第1層（構造）には受け入れる。文体の混入は「完成文を使わない」ことで原理的に防ぐ。

### 5.1 3層データセット

推論は Step1（構造）/ Step2（表現）に分かれているのに、学習データが1層に潰れているのが
構造的欠陥。学習側を推論側と同じ層構造に揃える。

| 層 | コレクション | 内容 |
|---|---|---|
| **第1層 構造** | `dataset_structure` | `odai` → `toku` + `kokoro`（**完成文は使わない**） |
| **第2層 反応** | `persona_reactions` | ペルソナ版 × 構造 × 完成文 → 人間の反応 |
| **第3層 訂正** | `correction_pairs` | 人間が直した差分（赤ペン） |

**層の追加を前提に**、3コレクションへ共通エンベロープを持たせる:

```
{
  dataset_layer: "structure" | "reaction" | "correction" | ...,
  schema_version: int,
  source_ref: { collection, doc_id },
  narrator_persona_id, narrator_persona_version_id,
  data_origin: "builtin" | "custom" | "no_data",
  owner_uid,
  created_at,
  payload: { ...層ごとの中身... }
}
```

### 5.2 第1層：出力形式の変更

| 経路 | 変更 |
|---|---|
| SFT(A) `tools/extract_training_data.py` | 出力を `odai → toku + kokoro` に変更（現在は完成文） |
| SFT(B) `extract_sft_data.py` | 同上。未配線だが同時に直す |
| DPO `extract_dpo_data.py` | §5.3 で対処 |

### 5.3 ガード1(b)：自己評価の除外と寄与上限

DPO の chosen/rejected は `user_feedbacks.overall_score`（Tier B）で決まる。
ここがカスタムペルソナ作成者による自己評価の入口になる。

| 対策 | 内容 |
|---|---|
| **自己評価の除外** | `user_feedbacks.owner_uid == narrator_persona.owner_uid` のペアを除外。**最も的確** |
| **寄与上限（二重）** | 1回の抽出で、単一 `owner_uid` 由来 ≤ 5%、単一 `narrator_persona_version_id` 由来 ≤ 5%。5体作成でも合計25%にならないよう owner 側を必ず併用 |
| 管理者キュレーション（Task1） | 人間のゲートがあるため上限不要 |

実装先は `extract_dpo_data.py` の `_dedupe()` 直後（サンプリング段）。

### 5.4 ガード3：サーキットブレーカーの分離

`quality_circuit_breaker.py` は `pipeline_id` 文字列単位でウィンドウが分離される設計。
**呼び出し側で `pipeline_id` にペルソナIDを含めるだけ**で分離が完成する。

```python
pipeline_id = f"{既存のpipeline_id}::{narrator_persona_id}"
```

> **未確認**: 呼び出し元の特定が調査範囲外。Phase 0 で確認する。

### 5.5 第2層の入力源

| 源 | 現状 | 変更 |
|---|---|---|
| 座布団（`timeline.py`） | `zabuton_count` を `Increment(1)` するのみ。誰が押したかの記録なし、サーバー側重複排除なし | 反応ごとに `persona_reactions` へ1レコード追加。**既存カウントは初期値として保持し、新規分から個別記録を積む** |
| `user_feedbacks` | `overall_score` + `axis_feedback` | `narrator_persona_version_id` を付与 |
| `human_evaluations`（SQLite） | 有効8件のみ、形状が現行コードと非互換で事実上デッド | **使わない** |

### 5.6 第3層：2系統を統合

赤ペンが2系統あり、連携していない。**両方を `correction_pairs` に正規化する**。

| | 系統A `corrections`（Firestore） | 系統B `origin_type=="user_akapen"`（SQLite） |
|---|---|---|
| 差分の形 | **1レコードに before/after 両方** | `source_item_id` で2行を突き合わせ |
| 評価スコア | 付かない | **付く**（訂正が改善かを検証できる） |

系統B側では**訂正前後の `s_total` 差分を付与**する。ユーザーの訂正が必ずしも改善とは
限らないため、教師信号の品質管理に使う。

> 書き込み口の一本化は別タスクとする（今回は読み取り側の統合に留める）。

### 5.7 `data_origin` タグ

除外用ではなく**分析・追跡用**。問題のあるペルソナが後から判明した際に、
`narrator_persona_version_id` と併せて**遡及的に該当データを特定・除去できる**。

---

## 6. 認証と所有者識別

Firebase 匿名認証は実装済み。**適用範囲を拡張する**（新規実装ではない）。

| 項目 | 内容 |
|---|---|
| 拡張範囲 | 掲示板投稿のみ → **ペルソナ関連API全般** |
| 検証 | バックエンドで `verify_id_token`。Firestore ルールは deny-all のままでよい |
| 所有者判定 | **必ず Firebase UID**。`user_slug`（localStorage、サーバー検証なし）は使わない |
| 表示名 | `user_slug` / 赤ペンの `pen_name` は `owner_display_name` として表示専用 |
| 上限 | 1 UID あたり **5件** |

### 6.1 引き継ぎコード

匿名認証UIDはブラウザストレージに紐づくため、端末変更やデータ消去で失われる。
**マイペルソナを別端末へ移すための仕組み。**

- 発行側で `A3K7-9PQR` 形式のコードを表示
- 別端末で入力すると `narrator_personas.owner_uid` を新UIDへ移管
- **24時間有効・1回使い切り**
- UIに「このブラウザに保存されています」と明示

### 6.2 認可ルール（サーバー側で強制）

```
参照可: is_builtin == true  ∪  owner_uid == 自分
更新可: owner_uid == 自分
削除可: owner_uid == 自分 かつ is_deletable == true   ← 満たさなければ 403
並替可: 自分から見える範囲のみ
```

---

## 7. API

### 7.1 エンドポイント（`apps/persona_router`）

| メソッド | パス | 内容 |
|---|---|---|
| GET | `/v1/personas` | **変更**: UID を見て「組み込み ＋ 自分」を `sort_order` 順で返す |
| GET | `/v1/personas/schema` | **新規**: 設定項目定義＋ツールチップ本文 |
| POST | `/v1/personas/draft` | **新規**: 名前から Gemini で初期設定を生成（保存しない） |
| POST | `/v1/personas` | **新規**: 作成（上限5件チェック） |
| PATCH | `/v1/personas/{id}` | **新規**: 新バージョン追加 |
| DELETE | `/v1/personas/{id}` | **新規**: 論理削除 |
| PUT | `/v1/personas/order` | **新規**: 並び順の一括更新 |
| POST | `/v1/personas/transfer-code` | **新規**: 引き継ぎコード発行 |
| POST | `/v1/personas/transfer` | **新規**: 引き継ぎコード適用 |

### 7.2 既存バグの同時修正

管理コクピットの上書き機能（`admin_config.py` が書く `persona_overrides`）は
**persona_router にしか反映されていない**。evaluator の `generate.py:575` と
`ondemand_elyza_worker.py:280` はハードコード辞書を直読みしている。

**全経路を `get_personas(db)` 相当に寄せることで、この上書き機能が本来の意図通り動く。**

### 7.3 `persona_id` の型

`PERSONAS: dict[int, dict]` でキーは整数。カスタムは UUID なので**文字列に統一**する。

- 組み込みは `"1"`〜`"10"`
- API は互換のため int も受理し、内部で文字列に正規化
- **`PERSONAS.get(id, PERSONAS[1])` のフォールバックを廃止し 404 を返す**
  （存在しないIDが黙ってペルソナ1にすり替わると、記録と実際の生成が食い違う）

### 7.4 Gemini ドラフト生成

- モデル: **`gemini-3.5-flash`**（環境変数 `PERSONA_DRAFT_MODEL`）
- `thinking_level` は `low` または `minimal`
- **`temperature` / `top_p` / `top_k` は指定しない**（3.5以降は非推奨、3.6以降は無視）
- 単価（`cost_calculator.py` へ登録）: 入力 $1.50/1M、出力 $9.00/1M
- 構造化出力を強制し、`output_parser.py` 相当の頑健な JSON 抽出＋Pydantic 検証
- **失敗時はエラーにせず空テンプレートを返す**（手動入力へフォールバック）

### 7.5 プロンプトインジェクション対策

ユーザーが書いた `prompt` は step2 でシステムプロンプトとして使われる。

1. 名前は30文字・改行禁止
2. ドラフト生成時、ユーザー入力は「データ」として明確に区切る
3. `prompt` 保存時に長さ上限（2000文字）と禁止パターン検査
4. **アプリ側の固定プロンプトをユーザープロンプトより後に配置**（後勝ち構造）
5. `penalty.py` の段階的ブロックをドラフト生成・作成APIにも適用

---

## 8. フロントエンド

`apps/evaluator/frontend`（Vanilla JS、実行時ライブラリ依存なし）。**新規ライブラリを入れない。**

### 8.1 一覧：セクション分離

```
[マイペルソナ]                    [編集]
  （新しい順がデフォルト、↑↓で並替）
─────────────────────────
[アプリのペルソナ]
  （10体固定、編集トグルなし）
```

### 8.2 編集モード方式（D&D・長押しは採用しない）

| 通常時 | 編集モード時 |
|---|---|
| 名前のみ表示 | 各行に `↑` `↓` `🗑` を表示 |

- ジェスチャ判定・長押しタイマー・スクロール競合が**すべて消える**
- 上限5件なので端から端まで最大4タップ
- デスクトップでそのまま動く
- ボタンなのでキーボード操作・スクリーンリーダーが自動で効く
- 通常モードでは削除ボタンが存在しないため**構造的に誤爆しない**
- 実装は隣接2件の `sort_order` スワップを1リクエスト
- 削除には確認ダイアログを必ず挟む

### 8.3 新規作成時の並び順

`sort_order` を「現在の最小値 - 1」にする。既存行を1件も UPDATE せずに先頭挿入できる。

### 8.4 ツールチップ

- **`title` 属性は使わない**（モバイルで表示されない）
- 項目ラベルを `<button>` にし、クリックで説明パネルを開閉
- 説明文は `GET /v1/personas/schema` から取得（フロントにベタ書きしない）
- モバイルでは画面下部シート形式
- `aria-expanded` / `aria-describedby` を付与

### 8.5 ドラフト生成のUI

数秒かかるため、ボタンを無効化しスピナーを表示する（無反応だと連打される）。

---

## 9. インフラ整理

### 9.1 DBパスの一元化

`DEFAULT_DB_PATH = "nazokake_local.db"`（相対パス、`database.py:84`）が
カレントディレクトリ基準で解決されるためDBが散在している。

**`env_config.py` が持つ「ディレクトリツリーを遡って探索する」手法を流用し、
リポジトリルートからの絶対パス解決に変更する。** 起動時に解決後の絶対パスを必ずログ出力。

### 9.2 孤児DBの削除

`apps/batch_factory/nazokake_local.db`（128件）は**全件が root DB に同一 `doc_id` で存在し、
`updated_at` がマイクロ秒まで一致、`sync_status='synced'`**。固有データはゼロ。

→ **zip保管のうえ削除**。`.gitignore` に `*.db` を追加して再発を防ぐ。

### 9.3 Firestore 同期のマルチコレクション対応

現在の同期対象は `nazokake_items` のみ。以下4テーブルを**同期対象に追加する**:

- `audit_logs`（管理者操作の監査証跡）
- `trigger_state`
- `quality_circuit_breaker_state`
- `research_articles`（なぞかけ研究所の公開記事）

これらは現在 Cloud Run の `/tmp` にしかなく、**再起動のたびに失われている**。
Push・起動時Pull復元の両方を対象にする。

`firestore_sync.py` は単一コレクション前提の実装なので、**マルチコレクション対応への
拡張**が必要。本機能とは独立した改善のため Phase 1 に含める。

### 9.4 由来不明の Cloud Run サービス

`nazo-agent-api` / `nazokake-admin` / `nazokake-backend`(us-central1) の3つが
リポジトリのどのワークフローからも参照されず稼働中。すべて `allow-unauthenticated`。

**`nazo-agent-api` は `run/audit_reports/nazo_agent_daemon.log` の存在から、
開発用エージェントデーモンのバックエンドである可能性が高い。即削除は避ける。**

段階手順:
1. Cloud Monitoring で過去90日のリクエスト数を確認
2. URLのハードコード参照をリポジトリ全文検索
3. **`allow-unauthenticated` を解除**（この時点でリスクとコストはほぼ解消）
4. 2〜4週間様子見
5. 削除

### 9.5 デプロイ

persona_router の CI/CD は `33ab466` で新設済み。**新規タスクなし**。ただし確認:

- `packages/shared_core/**` の変更が**両サービスのデプロイを起動する**パスフィルタか
- Alembic マイグレーションの実行主体が1つに絞られているか（同時実行は競合する）
- `firestore.rules` は CI に含まれない（手動運用）。新コレクション追加後も deny-all の
  ままでよいが、**運用として明文化**する

---

## 10. フェーズ分割

各フェーズは独立してマージ可能。**Phase 0〜2 は本機能と独立しており先行着手できる。**

### Phase 0: 事前確認

1. `quality_circuit_breaker` の呼び出し元と、現在渡している `pipeline_id` の値
2. `tools/train_local_model.py` が実際に読むデータファイルの確定
3. 系統A `corrections` / 系統B `user_akapen` それぞれの件数実測

### Phase 1: 基盤整理（低リスク・先行実施）

1. DBパスを絶対パス解決に変更、起動時ログ出力
2. 孤児DBを zip 保管のうえ削除、`.gitignore` に `*.db`
3. `firestore_sync.py` をマルチコレクション対応にし、4テーブルを同期対象に追加
4. `persona_router` の docstring を「お題属性推定とルーティングシステム」に修正
5. ORM の `persona` 列 docstring に「廃止済み・書き込み禁止」を明記

**完了条件**: 再起動後も4テーブルの内容が復元されること

### Phase 2: 評価軸の削減とデータ移行

1. **先に117件を救出用の一時テーブル/JSONへ退避**（Phase 3 で使う）
2. `evaluation.py` / `schemas.py` から `S_persona` / `S_aufheben` を削除
3. 既存全件の `scores` JSON から2キーを削除し `s_total` を再計算
4. サーキットブレーカー発火率の監視を開始（切り替え前後の比較）

**完了条件**: 全件の `s_total` が11軸ベースになり、`scores` に2キーが残っていないこと

### Phase 3: audience persona の全廃と語り手ペルソナのリンク

1. Alembic で `nazokake_items` に4列追加（§3.5）
2. 移行スクリプト: 10件＋117件を `narrator_persona_id` へ、残りは `"No_Data"`
3. `PersonaMeta` から `big5` 必須制約を削除、4箇所のダミー構築コードを削除
4. `_to_persona_meta()` と `MASTER_PERSONA_BIG5_PLACEHOLDER` を削除
5. `persona` 列への書き込みを停止

**完了条件**: 127件の出自が判明し、batch_factory の生成が従来通り動くこと
**ロールバック**: `alembic downgrade` の動作確認をマージ条件にする

### Phase 4: 語り手ペルソナのデータ化

1. Firestore `narrator_personas` / `narrator_persona_versions` を定義
2. `narrator_personas.py`（shared_core）を新設。§3.3 のID設計と2関数
3. `PERSONAS[1..10]` を `is_builtin=true, is_deletable=false` で投入（冪等シード）
4. センチネル `"No_Data"` を persona / version 両方に作成
5. 全参照経路を `get_personas` 相当へ寄せる（§7.2 の既存バグ修正を含む）
6. `persona_id` を文字列に統一、フォールバック廃止 → 404

**完了条件**: 管理者のペルソナ上書きが evaluator 経路にも反映されること

### Phase 5: 生成パスへの記録

1. 3経路（persona_router / evaluator / ELYZAワーカー）で version_id を記録
2. **ジョブペイロードに version_id とプロンプトのスナップショットを追加**（§3.4）
3. `pipeline_id` にペルソナIDを含める（§5.4）

**完了条件**: 新規生成分に正しい version_id が入り、旧形式ジョブでも落ちない

### Phase 6: マイペルソナ API

1. §7.1 の9エンドポイント
2. §6.2 の認可（403は `is_deletable` で判定）
3. 匿名認証の適用範囲を拡張、引き継ぎコード
4. Gemini ドラフト生成（§7.4）とインジェクション対策（§7.5）
5. テスト（§11）

### Phase 7: フロントエンド

1. OpenAPI 再生成
2. セクション分離した一覧、新しい順デフォルト
3. 編集モード（↑↓・削除）
4. 作成フォームとツールチップ
5. 実機（iOS/Android）確認

### Phase 8: 3層データセット

1. 共通エンベロープの定義
2. 第1層: SFT(A)(B) の出力を `odai → toku + kokoro` に変更
3. 第1層: DPO に自己評価除外と寄与上限を実装（§5.3）
4. 第2層: `persona_reactions` 新設、座布団を「1反応＝1レコード」に変更
5. 第3層: `correction_pairs` に系統A/Bを統合、スコア差分を付与
6. 管理コクピットに層別の集計ビュー

### Phase 9: インフラ後片付け

1. Cloud Run 3サービスの棚卸し（§9.4 の段階手順）
2. `PROJECT_CORE.md` の更新（DB構成の記述が実装と乖離している）

---

## 11. テスト

`apps/persona_router` にはテストが存在しない。本機能を機に基盤を導入する。
CI（`pyright_check.yml`）が `tests/` を実行するため `tests/persona_router/` に置けば自動で回る。

| 分類 | 内容 |
|---|---|
| 認可 | 他人のペルソナが一覧に出ない／PATCH・DELETE できない（403） |
| 認可 | **組み込み10体を DELETE できない（403）** |
| 上限 | 6件目の作成が拒否される |
| 不変性 | 同一設定の再保存で version が増えない |
| 不変性 | 編集後、旧 version の内容が不変 |
| 不変性 | 編集後、過去のなぞかけが編集前 version を指す |
| 移行 | 10件＋117件が救出され、残りが `"No_Data"` |
| 移行 | 全件の `s_total` が11軸で再計算される |
| 記録 | 3経路すべてで version_id が記録される |
| 記録 | 旧形式ジョブでもワーカーが落ちない |
| ドラフト | 不正JSONでクラッシュせず空テンプレートを返す |
| 学習 | 自己評価ペアが DPO 抽出から除外される |
| 学習 | 単一 owner の寄与が上限を超えない |
| 引き継ぎ | コードが24時間で失効し、2回目は使えない |
| 論理削除 | 削除後も過去のなぞかけが表示できる |

---

## 12. 積み残し（本計画のスコープ外）

| # | 事項 |
|---|---|
| 1 | `WebGemini (Manual)` 39件の起源が不明（現行コード・git全履歴に該当なし） |
| 2 | 赤ペン2系統の**書き込み口**の一本化（今回は読み取り側の統合のみ） |
| 3 | `human_evaluations` の旧8件（現行コードと非互換、事実上デッド） |
| 4 | `research_articles` / `trigger_state` の物理スキーマとORM宣言の型不一致（DATETIME vs String） |
| 5 | `PROJECT_CORE.md` のDB構成記述が実装と乖離 |

---

## 付録: Claude Code への依頼方法

フェーズ単位で依頼し、**一度に複数フェーズを渡さない**。

```
docs/plan_persona_feature_v3.md の Phase N のみを実装してください。
Phase N+1 以降には手を付けないこと。

実装前に、計画と実装が食い違う点があれば着手前に報告してください。
完了後、§11 のテストのうち Phase N に該当するものを追加し、実行結果も報告してください。
```

**Phase 2 と Phase 3 は既存データを破壊的に変更する**ため、実行前に
`nazokake_local.db` の zip バックアップを取ること。
