# GCP事前構築手順書: WIF + Artifact Registry + Container Analysis (instructions/004)

`.github/workflows/deploy_cloud_run.yml` がGitHub Actionsから安全にGCPへデプロイ
できるようにするため、人間のオペレーターがGCPコンソールまたは`gcloud` CLIで
**事前に一度だけ**実行しておくべき手順。このドキュメントの手順自体はAIエージェントが
自律実行しない(GCP IAM・課金に影響する変更のため、人間の実行を前提とする)。

**このセッションでの検証範囲についての正直な注記:** この開発機にはGCPへの認証済み
アクセスが無く、以下の`gcloud`コマンド群はこのセッション内で実行・動的検証していない
(`infra/verification_env/README.md`と同じ位置づけ)。実行後は必ず
[動作確認](#動作確認)の節でパイプラインが実際に通ることを確認すること。

## 0. 前提

- 対象プロジェクト: `nazokakeapp-137e5`(既存、`docs/DEPLOYMENT.md`参照)。
- `gcloud auth login` 済み、かつ `gcloud config set project nazokakeapp-137e5` 済み。
- 以下の`<GITHUB_ORG>/<GITHUB_REPO>`は実際のGitHubリポジトリのowner/repo名に
  置き換えること(このリポジトリには現在GitHubリモートが設定されていないため、
  本手順書では実在するリポジトリ名を断定的に記載しない)。

## 1. 必要なAPIの有効化

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com \
  containeranalysis.googleapis.com \
  ondemandscanning.googleapis.com \
  --project=nazokakeapp-137e5
```

`containeranalysis.googleapis.com`(Container Analysis本体)と
`ondemandscanning.googleapis.com`(`gcloud artifacts docker images scan`が使う
On-Demand Scanning API)の両方が必要(instructions/004要件)。

## 2. Artifact Registry リポジトリの作成

`docs/DEPLOYMENT.md`の既存手順と同一(`nazo-agent`リポジトリが既に存在する場合は
このステップをスキップする):

```bash
gcloud artifacts repositories create nazo-agent \
  --repository-format=docker \
  --location=asia-northeast1 \
  --description="Nazo-Agent コンテナイメージ(GitHub Actions WIF経由のPushも含む)" \
  --project=nazokakeapp-137e5
```

## 3. Workload Identity Pool / Provider の作成

```bash
PROJECT_ID="nazokakeapp-137e5"
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')

# 3-1. Pool作成
gcloud iam workload-identity-pools create "github-actions-pool" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --display-name="GitHub Actions Pool"

# 3-2. Provider作成(OIDC、GitHub Actions発行のトークンを受け付ける)
gcloud iam workload-identity-pools providers create-oidc "github-actions-provider" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --workload-identity-pool="github-actions-pool" \
  --display-name="GitHub Actions Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --issuer-uri="https://token.actions.githubusercontent.com"
```

**このProviderに対する属性条件(attribute-condition)は必ず設定すること。** 未設定の
場合、GitHub上の *任意の* リポジトリのOIDCトークンでこのプロバイダを通過できてしまう
(WIFの既知の設定ミスパターン)。対象を自リポジトリ・mainブランチへのpushのみに絞る:

```bash
gcloud iam workload-identity-pools providers update-oidc "github-actions-provider" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --workload-identity-pool="github-actions-pool" \
  --attribute-condition="assertion.repository == '<GITHUB_ORG>/<GITHUB_REPO>' && assertion.ref == 'refs/heads/main'"
```

## 4. CI/CD用サービスアカウントの作成と、なりすまし(impersonation)許可

```bash
gcloud iam service-accounts create "github-actions-deployer" \
  --project="${PROJECT_ID}" \
  --display-name="GitHub Actions Cloud Run Deployer"

DEPLOYER_SA="github-actions-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
WORKLOAD_IDENTITY_POOL_ID="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-actions-pool"

# 4-1. WIF経由でこのサービスアカウントになりすます(impersonate)権限を、
# 自リポジトリのOIDC subjectのみに限定して付与する(instructions/004要件、
# roles/iam.workloadIdentityUserのバインディング)。
gcloud iam service-accounts add-iam-policy-binding "${DEPLOYER_SA}" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${WORKLOAD_IDENTITY_POOL_ID}/attribute.repository/<GITHUB_ORG>/<GITHUB_REPO>"
```

`google-github-actions/auth@v2` の `workload_identity_provider` 入力には、以下の
完全なProviderリソース名を、GitHub Secretsの `WIF_PROVIDER` として登録する:

```
projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-actions-pool/providers/github-actions-provider
```

`service_account` 入力には `${DEPLOYER_SA}` の値を GitHub Secrets の
`WIF_SERVICE_ACCOUNT` として登録する。

## 5. サービスアカウントへの最小権限付与

`github-actions-deployer` に付与するロールは、パイプラインの各ステップが必要とする
最小権限に限定する(instructions/004要件):

```bash
for ROLE in \
  "roles/artifactregistry.writer" \
  "roles/run.admin" \
  "roles/iam.serviceAccountUser" \
  "roles/containeranalysis.occurrences.viewer"
do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOYER_SA}" \
    --role="${ROLE}"
done
```

| ロール | 用途 |
|---|---|
| `roles/artifactregistry.writer` | ビルドしたイメージをArtifact Registryへpush |
| `roles/run.admin` | Cloud Runサービスへのデプロイ |
| `roles/iam.serviceAccountUser` | Cloud Runの実行サービスアカウント(`docs/DEPLOYMENT.md`が設定する`${PROJECT_NUMBER}-compute@developer.gserviceaccount.com`)へのデプロイ時のact-as |
| `roles/containeranalysis.occurrences.viewer` | `gcloud artifacts docker images list-vulnerabilities` によるスキャン結果の取得 |

`roles/secretmanager.secretAccessor` は**このCI/CD用サービスアカウントには付与しない**
(Cloud Runの実行時サービスアカウントのみが必要とする権限であり、既に
`docs/DEPLOYMENT.md`の手順で付与済み。デプロイ実行者への過剰な権限付与を避ける)。

## 6. GitHub側の設定

リポジトリの Settings → Secrets and variables → Actions に以下を登録する:

- `WIF_PROVIDER`: 手順4で示した完全なProviderリソース名
- `WIF_SERVICE_ACCOUNT`: `github-actions-deployer@nazokakeapp-137e5.iam.gserviceaccount.com`

サービスアカウントキーJSON(`credentials.json`等)はGitHub Secretsに一切登録しない
(WIFの目的そのものであり、登録してしまうとこの構成全体の意味が失われる)。

## 動作確認

1. `apps/`配下に変更を加えたコミットを`main`へpushする。
2. GitHub Actionsの実行ログで、`auth`ステップが `WIF_PROVIDER`/`WIF_SERVICE_ACCOUNT`
   経由でエラー無くGCPアクセストークンを取得できることを確認する。
3. Artifact Registry (`nazo-agent`リポジトリ)に、コミットSHAタグのイメージが
   実際にpushされていることを確認する:
   ```bash
   gcloud artifacts docker images list \
     asia-northeast1-docker.pkg.dev/nazokakeapp-137e5/nazo-agent
   ```
4. 脆弱性スキャンステップのログに、実際のスキャン結果件数(0件、またはCRITICAL/HIGH
   検出時の強制停止)が出力されることを確認する。
5. Cloud Runサービス(`nazokake-backend`)のリビジョンが更新されていることを確認する:
   ```bash
   gcloud run services describe nazokake-backend --region=asia-northeast1 \
     --format='value(status.latestReadyRevisionName)'
   ```

## 既知の制約・フォローアップ事項

- `.github/workflows/deploy_cloud_run.yml`のワークフロー内コメントに記載の通り、
  現状`apps/evaluator/`はこのスーパープロジェクトの`.gitignore`で除外されており、
  `actions/checkout`では取得されない。本パイプラインを実運用する前に、対象アプリを
  このリポジトリのgit管理下に含めるか、`DOCKERFILE_PATH`をgit管理下の別アプリ
  (例: 将来`apps/tactical_cic`にDockerfileが追加された場合)へ向け直す必要がある。
- 属性条件(`assertion.repository == '<GITHUB_ORG>/<GITHUB_REPO>'`)の実際の値は、
  リポジトリのGitHubリモートが確定してから設定すること。
