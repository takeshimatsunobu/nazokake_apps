# 🏛️ NAZOKAKE-DOJO: PROJECT CORE (Single Source of Truth)

**最終更新:** 2026年6月 (Phase 3 アーキテクト純化完了版)
**アーキテクト:** Takeshi & Gem

---

## 1. システム概要 (System Overview)
本システムは、ユーザーから提供された「お題」に対して、AIが高品質な「なぞかけ」を生成し、その文化的背景・同音異義語の文脈を抽出し、11項目の独自評価軸で精密に採点（エバリュエーション）する、完全非同期型のWebアプリケーションである。

**【コア・コンセプト】**
管理者が孤独にデータを作るのではなく、一般ユーザーからの投稿や評価（道場破り）を通じてクラウドソーシングを行い、高品質なRLHF（強化学習）データを自律的に量産する「AI育成エコシステム」を構築する。

---

## 2. インフラストラクチャ・コンポーネント (Infrastructure)

### 🖥️ フロントエンド (Frontend)
* **アーキテクチャ:** 完全SPA (Single Page Application)
* **技術スタック:** HTML5 / CSS3 / Vanilla JavaScript
* **ホスティング:** Firebase Hosting
* **特徴:** `index.html` と `app_final.js` (または `app.js`) を中核とし、軽量かつ高速なレンダリングを実現。

### ⚙️ バックエンド (Backend)
* **アーキテクチャ:** RESTful API (Python 3)
* **技術スタック:** FastAPI, `httpx` (完全非同期対応)
* **ホスティング:** GCP Cloud Run (単一コンテナ統合型・ゼロスケール対応)
* **コアファイル:**
  * `backend/main.py`: エントリーポイント、CORS設定。
  * `backend/api/endpoints.py`: ルーティング、フロントエンドとのI/O接点。
  * `backend/services/ai_service.py`: デュアルAIルーティング、プロンプト構築、エラーハンドリングの本丸。

### 🗄️ データベース (Database)
* **技術スタック:** Firebase Firestore (NoSQL)
* **主要コレクション:** `nazokake_items`, `seed_odai` (お題リスト), `system_config`
* **状態管理:** `status` フィールドを用いた厳格なステートマシン（0: 初期状態, 2: 完了, -1/error: エラー等）。

---

## 3. デュアルAIアーキテクチャ (Dual-AI Engine)

推論能力とコストを最適化するため、ローカルAIとクラウドAPIをシームレスに連携させた「バケツリレー方式（フォールバック機構）」を採用。

### 🛡️ Tier 1: 高速・低コスト生成 (GCP L4要塞)
* **役割:** なぞかけの基本生成、文化背景の高速抽出。
* **環境:** 動的確保される GCP Compute Engine (g2-standard-4, L4 GPU x1)
* **エンジン:** `llama-server` 
* **モデル:** `gemma-2-9b-it-Q4_K_M.gguf` (ローカルGemma)
* **接続要件:** タイムアウト3.0秒の「フェイルファスト」設定。環境変数 `GCP_L4_IP` により動的にルーティング。

### ☁️ Tier 2: 高度推論・審査担当 (Cloud Gemini API)
* **役割:** Tier 1無応答時のフォールバック生成、および最高峰の11軸精密採点（JSON講評出力）。
* **環境:** Google Cloud GenAI API (`google-genai` SDK)
* **モデル:** `gemini-3.1-pro-preview` (評価用), `gemini-3.5-flash` (生成用)

---

## 4. MLOps & 今後のロードマップ (Roadmap)

1. **データパイプラインの完成:** Firestore上の高評価データ(status: 2)を抽出し、JSONLフォーマットでDPO/SFT学習データに変換する自動化。
2. **モデルのファインチューニング:** 抽出したデータを元に、GCP Vertex AIやColab上で独自モデルを育成。
3. **RAG（検索拡張生成）の統合:** 過去の傑作なぞかけをベクトル検索し、評価のブレ防止や生成品質の底上げを行う。

---

## 5. 絶対制約 (Architectural Guardrails)
AIエージェント、および開発者は、コード改修時に以下のルールを絶対に破ってはならない。

1. **IPハードコードの禁止:** GCP要塞のIPは必ず `.env` (GCP_L4_IP等) から取得する。
2. **完全なるエラーキャッチ (サイレント・デス撲滅):** 非同期処理 (`ai_service.py`等) で例外が発生した際は、`return`で逃げず、必ずFirestoreに `status: "error"` と理由を書き込み、無限ロードを防ぐ。
3. **Firestoreの厳格な型管理:** `orderBy`使用時の暗黙の除外（サイレント・ドロップ）を防ぐため、Timestamp型や必須フィールドの欠損を許さない。
4. **一撃必殺の原則:** 手作業でのコード置換を禁じ、パッチは常に完全な関数単位・ファイル単位のコード出力とPowerShellコマンドで行う。
5. **推測の排除:** AIはコードを書く前に必ず `Get-Content` 等で現状のファイルをダンプし、事実（ファクト）に基づいてのみ修正を行う。
