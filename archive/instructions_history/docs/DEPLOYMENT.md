# デプロイ手順書 (nazokake-backend / Cloud Run)

`apps/evaluator/backend`(なぞかけディスカバリー API)を Google Cloud Run へ
デプロイするための手順。コンテナ定義は `apps/evaluator/Dockerfile`、依存関係の
ロックは `apps/evaluator/backend/uv.lock` を使用する。

**Canonical(正)なデプロイ手順は `.github/workflows/deploy_cloud_run.yml`
(GitHub Actions、Workload Identity Federation)である。** `apps/**` への
`main`ブランチへのpushをトリガーに、ビルド→Artifact Registryへのpush→
CRITICAL/HIGH脆弱性のハード・フェイルゲート→Cloud Runへのデプロイが自動実行される
(instructions/218)。`cloudbuild.yaml`(リポジトリルート、`gcloud builds submit`)は
脆弱性スキャンゲートを経由しないため、本番への正規のデプロイ手段としては使用しない
(5節参照)。

---

## 1. 前提

- GCPプロジェクトが作成済みであること(既存のFirebaseプロジェクト
  `nazokakeapp-137e5` を想定。`main.py`の`firebase_admin.initialize_app`が
  このプロジェクトIDを直接参照している)。
- GitHubリモートが設定済みであること(`takeshimatsunobu/nazokake_apps`)。
- `gcloud` CLIがインストール・認証済みであること(`gcloud auth login`)。初回セットアップ
  (下記2節)を人間のオペレーターが手元で実行する場合のみ必要で、日常のデプロイ自体は
  GitHub Actions側で完結する(ローカルの`gcloud`認証には依存しない)。

## 2. 初回セットアップ(WIF・Artifact Registry・Secret Manager) — 一度だけ

必要なGCP側リソース(API有効化・Artifact Registryリポジトリ・Workload Identity
Federation・CI/CD用サービスアカウント・IAM権限・Secret Manager)は、人間のための
チェックリストではなく、コピペして実行可能なIaCスクリプトとして
`infra/scripts/setup_gcp_wif_and_secrets.sh` に用意している(instructions/218)。

```bash
# GEMINI_API_KEY / ANTHROPIC_API_KEY の実際の値を対話的に入力してから実行する
# (スクリプト自体に秘密値はハードコードされていない)
bash infra/scripts/setup_gcp_wif_and_secrets.sh
```

このスクリプトは冪等(既存リソースがあればスキップ)であり、実行後に必要な
GitHub Secrets(`WIF_PROVIDER`・`WIF_SERVICE_ACCOUNT`)の値を最後に出力する。
設計・IAMロールの根拠は `infra/docs/gcp_wif_artifact_registry_setup.md` を参照。

> **`serviceAccountKey.json`について**: Cloud Run上では登録しない。
> `firebase_admin.initialize_app(options={'projectId': ...})`は明示的な鍵ファイル
> 無しで呼ばれており、Application Default Credentials(Cloud Runの実行サービス
> アカウント自身のIAM権限)でFirestore/Firebase Admin SDKを認証する設計になって
> いる。実行サービスアカウントには`roles/datastore.user`等、Firestoreアクセスに
> 必要なロールが上記スクリプトにより付与される。

## 3. 依存関係の決定論的ロック(uv)

`apps/evaluator/backend`の依存関係は`uv`で管理し、`uv.lock`(Git管理対象)へ
推移的依存を含めて全バージョンを固定している(instructions/218)。
`apps/evaluator/Dockerfile`のビルドステージは`uv sync --frozen`のみでインストール
するため、`uv.lock`を更新しない限りビルド結果は変わらない。

依存関係を追加・変更した場合は、必ずロックファイルを再生成してコミットすること:

```bash
cd apps/evaluator/backend
uv lock
```

`uv sync --frozen`はロックファイルと`pyproject.toml`の定義が一致しない場合、
ビルド自体を失敗させる(ロック更新漏れの検知)。

## 4. デプロイの実行(自動・Canonical経路)

`apps/`配下に変更を加えたコミットを`main`へpushするだけでよい。GitHub Actions
(`.github/workflows/deploy_cloud_run.yml`)が自動的に:

1. WIF経由でGCPへ認証(サービスアカウントキーJSONは使用しない)
2. `apps/evaluator/Dockerfile`をビルド(`uv sync --frozen`で決定論的に依存解決)
3. Artifact Registryへpush
4. CRITICAL/HIGH脆弱性のハード・フェイルゲート(検出時はデプロイを中止)
5. Cloud Runへ`nazokake-backend`としてデプロイ

進行状況はGitHubリポジトリのActionsタブで確認する。

## 5. ローカルでのビルド確認(本番デプロイの代替手段ではない)

`cloudbuild.yaml`はDockerfileの変更をCIを待たずに素早く確認したい場合のローカル
ビルド確認用であり、**脆弱性スキャンゲートを経由せずに本番Cloud Runサービスへ直接
デプロイしてしまう**ため、日常のデプロイ手段としては使用しないこと。動作確認のみが
目的なら、別のサービス名を明示的に指定して本番サービスへの誤デプロイを避けること:

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_SERVICE_NAME=nazokake-backend-canary .
```

## 6. デプロイ後の確認

```bash
gcloud run services describe nazokake-backend --region=asia-northeast1 --format='value(status.url)'
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
- GitHub Actionsワークフロー自体が実際にpush-to-deployまで通ることは、GCP/GitHub
  側のWIF設定(2節のスクリプト実行結果)が確定するまでこの開発機では動的に検証
  できていない。初回運用時は`main`への軽微な`apps/**`変更で一度通し、
  Actionsのログと本節6の確認コマンドの両方で成功を確認すること。
