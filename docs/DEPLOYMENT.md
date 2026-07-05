# デプロイ手順書 (nazo-agent-api / Cloud Run)

`apps/evaluator/backend`(なぞかけディスカバリー API)を Google Cloud Run へ
デプロイするための手順。ビルドは `cloudbuild.yaml`(リポジトリルート)、
コンテナ定義は `apps/evaluator/Dockerfile` を使用する。

---

## 1. 前提

- GCPプロジェクトが作成済みであること(既存のFirebaseプロジェクト
  `nazokakeapp-137e5` を想定。`main.py`の`firebase_admin.initialize_app`が
  このプロジェクトIDを直接参照している)。
- `gcloud` CLIがインストール・認証済みであること(`gcloud auth login`)。
- 対象プロジェクトが選択されていること: `gcloud config set project <PROJECT_ID>`

## 2. 必要なGCP APIの有効化

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  firestore.googleapis.com
```

## 3. Artifact Registry リポジトリの作成

```bash
gcloud artifacts repositories create nazo-agent \
  --repository-format=docker \
  --location=asia-northeast1 \
  --description="Nazo-Agent コンテナイメージ"
```

## 4. Secret Manager でのAPIキー登録

`.env`に平文で保存している`GEMINI_API_KEY`・`ANTHROPIC_API_KEY`は、
イメージには一切含めず(Dockerfile参照)、Secret Managerへ登録した上で
Cloud Runの`--set-secrets`経由で実行時に注入する。

```bash
# GEMINI_API_KEY を登録(既存の.envの値を使う場合。改行を含めないよう -n を推奨)
printf '%s' "<実際のGEMINI_API_KEYの値>" | gcloud secrets create GEMINI_API_KEY --data-file=-

# ANTHROPIC_API_KEY も同様に登録
printf '%s' "<実際のANTHROPIC_API_KEYの値>" | gcloud secrets create ANTHROPIC_API_KEY --data-file=-

# 既存シークレットの値を更新する場合は create の代わりに versions add を使う
# printf '%s' "<新しい値>" | gcloud secrets versions add GEMINI_API_KEY --data-file=-
```

Cloud Buildの実行サービスアカウント、およびCloud Runの実行サービスアカウントの
両方に、これらシークレットへの`Secret Manager のシークレット アクセサー`
(`roles/secretmanager.secretAccessor`)ロールを付与すること:

```bash
PROJECT_NUMBER=$(gcloud projects describe <PROJECT_ID> --format='value(projectNumber)')

for SECRET in GEMINI_API_KEY ANTHROPIC_API_KEY; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
done
```

> **`serviceAccountKey.json`について**: Cloud Run上では登録しない。
> `firebase_admin.initialize_app(options={'projectId': ...})`は明示的な鍵ファイル
> 無しで呼ばれており、Application Default Credentials(Cloud Runの実行サービス
> アカウント自身のIAM権限)でFirestore/Firebase Admin SDKを認証する設計になって
> いる。実行サービスアカウントに`roles/datastore.user`等、Firestoreアクセスに
> 必要なロールを付与しておくこと。

## 5. ビルド・デプロイの実行

リポジトリルートから実行する(`cloudbuild.yaml`はリポジトリルート基準の
ビルドコンテキストを前提としている):

```bash
gcloud builds submit --config=cloudbuild.yaml .
```

必要に応じてリージョン・サービス名を上書きできる:

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_REGION=asia-northeast1,_SERVICE_NAME=nazo-agent-api .
```

初回実行時、`cloudbuild.yaml`のDeployステップが自動的に:
1. `apps/evaluator/Dockerfile`をリポジトリルートをビルドコンテキストとして、
   `--build-context sharedcore=packages/shared_core`でnazokake_coreを取り込みつつ
   ビルド
2. Artifact Registryへpush
3. Cloud Runへ`nazo-agent-api`としてデプロイ(Secret Managerから
   `GEMINI_API_KEY`/`ANTHROPIC_API_KEY`を環境変数として注入)

## 6. デプロイ後の確認

```bash
gcloud run services describe nazo-agent-api --region=asia-northeast1 --format='value(status.url)'
```

得られたURLに対して、ヘルスチェックエンドポイントを叩いて起動確認する:

```bash
curl https://<デプロイされたURL>/api/health
# {"status":"ok"} が返れば正常
```

## 7. 既知の制約・今後の課題

`docs/TECHNICAL_DEBT.md`も参照。デプロイに直接関わる点として:

- Cloud Runはリクエストが無いと自動的にコンテナがスケールインする。Phase 4の
  Lv.1/Lv.2自己進化状態(Few-shotプールへの高評価データ・動的補正プロンプト)は
  プロセス内メモリにのみ存在するため、**スケールイン/再起動のたびにリセットされる**。
  永続化(Firestoreへの保存+起動時ロード)を行うまでは、本番運用での自己進化効果は
  限定的である点に留意する。
- `user_feedbacks`/`system_costs`コレクション用のFirestore複合インデックスが
  未作成。初回に実データでこれらのクエリを実行した際、`FAILED_PRECONDITION`
  エラーが発生する可能性がある。エラーメッセージ中のリンクからインデックスを
  作成するか、事前に`firestore.indexes.json`へ追記して`firebase deploy --only firestore:indexes`
  を実行しておくこと。
- MCPサーバー(`backend/mcp_server.py`)はStdio経由で動作する別プロセスであり、
  このCloud Runイメージには含まれるが自動起動はされない(FastAPIアプリとは
  独立したエントリポイントのため)。外部AIクライアントから利用する場合は、
  別途起動方法を検討すること。
