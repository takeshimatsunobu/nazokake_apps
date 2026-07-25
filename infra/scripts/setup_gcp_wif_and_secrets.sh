#!/usr/bin/env bash
# infra/scripts/setup_gcp_wif_and_secrets.sh
# =============================================
# GitHub Actions(WIF)によるCloud Runデプロイパイプラインが必要とするGCP側リソース
# 一式を、コピペして実行可能な単一の冪等スクリプトとして提供する(instructions/218)。
#
# 【背景】infra/docs/gcp_wif_artifact_registry_setup.md はこれまで「人間のための
# チェックリスト」(手順書に沿って1コマンドずつコピペする形式)だった。これを廃止し、
# 本スクリプト1本の実行に一本化する(手順書とコマンドの二重メンテナンスによる
# ドリフトを防ぐ。instructions/216で発見したドキュメント陳腐化と同じ問題を、
# 構造的に再発しないようにする)。
#
# 【実行主体】このスクリプトはAIエージェントが自律実行しない。GCP IAM・課金に
# 影響する変更(WIF Pool/Provider・サービスアカウント・IAM権限・Secret Manager)を
# 伴うため、人間のオペレーターが手元で一度だけ実行することを前提とする
# (infra/verification_env/setup_verification_env.shと同じ位置づけ)。
#
# 【冪等性】何度実行しても安全。既存リソースは作成をスキップし、IAMポリシー
# バインディングは(gcloudのadd-iam-policy-bindingが元々冪等なため)常に再適用する。
# Secret Managerの値だけは例外で、既存シークレットへは既定では触れない(意図しない
# ローテーションを避けるため)。ローテーションしたい場合は ROTATE_SECRETS=1 を付けて
# 再実行する。
#
# 【シークレットの取り扱い】GEMINI_API_KEY・ANTHROPIC_API_KEYの値は本スクリプトへ
# 一切ハードコードしない。対話プロンプト(read -rs、画面にも履歴にも残らない)で
# 都度入力を受け取る。旧手順書の `printf '%s' "<値>" | gcloud secrets create ...`
# という一行コマンド方式は、シェル履歴に平文の値が残る弱点があったため、本スクリプト
# ではこの方式を採用しない。
#
# 使い方:
#   bash infra/scripts/setup_gcp_wif_and_secrets.sh
#   ROTATE_SECRETS=1 bash infra/scripts/setup_gcp_wif_and_secrets.sh   # 既存シークレットの値を更新する場合

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-nazokakeapp-137e5}"
REGION="${REGION:-asia-northeast1}"
REPOSITORY="${REPOSITORY:-nazo-agent}"
SERVICE_NAME="${SERVICE_NAME:-nazokake-backend}"
GITHUB_REPOSITORY_SLUG="${GITHUB_REPOSITORY_SLUG:-takeshimatsunobu/nazokake_apps}"
WIF_POOL_ID="${WIF_POOL_ID:-github-actions-pool}"
WIF_PROVIDER_ID="${WIF_PROVIDER_ID:-github-actions-provider}"
DEPLOYER_SA_NAME="${DEPLOYER_SA_NAME:-github-actions-deployer}"
ROTATE_SECRETS="${ROTATE_SECRETS:-0}"

DEPLOYER_SA="${DEPLOYER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=== [0/7] 前提確認 ==="
gcloud config set project "${PROJECT_ID}" >/dev/null
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo "[OK] project=${PROJECT_ID} (number=${PROJECT_NUMBER}) / github=${GITHUB_REPOSITORY_SLUG}"

echo "=== [1/7] 必要なGCP APIの有効化(冪等) ==="
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  firestore.googleapis.com \
  iamcredentials.googleapis.com \
  containeranalysis.googleapis.com \
  ondemandscanning.googleapis.com \
  --project="${PROJECT_ID}"

echo "=== [2/7] Artifact Registry リポジトリ(冪等) ==="
if gcloud artifacts repositories describe "${REPOSITORY}" \
    --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "[OK] Artifact Registryリポジトリ '${REPOSITORY}' は既に存在します(スキップ)。"
else
  gcloud artifacts repositories create "${REPOSITORY}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Nazo-Agent コンテナイメージ(GitHub Actions WIF経由のPushも含む)" \
    --project="${PROJECT_ID}"
fi

echo "=== [3/7] Workload Identity Pool / Provider(冪等) ==="
if gcloud iam workload-identity-pools describe "${WIF_POOL_ID}" \
    --project="${PROJECT_ID}" --location="global" >/dev/null 2>&1; then
  echo "[OK] Workload Identity Pool '${WIF_POOL_ID}' は既に存在します(スキップ)。"
else
  gcloud iam workload-identity-pools create "${WIF_POOL_ID}" \
    --project="${PROJECT_ID}" \
    --location="global" \
    --display-name="GitHub Actions Pool"
fi

WORKLOAD_IDENTITY_POOL_ID="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL_ID}"

# 【必須の安全対策】attribute-conditionを自リポジトリ・mainブランチへのpushのみに
# 限定する(未設定の場合、GitHub上の任意のリポジトリのOIDCトークンでこのプロバイダを
# 通過できてしまうWIFの既知の設定ミスパターン)。既存の場合もupdate-oidcで毎回
# 再適用し、値のドリフトを防ぐ(冪等)。
if gcloud iam workload-identity-pools providers describe "${WIF_PROVIDER_ID}" \
    --project="${PROJECT_ID}" --location="global" --workload-identity-pool="${WIF_POOL_ID}" >/dev/null 2>&1; then
  echo "[INFO] Provider '${WIF_PROVIDER_ID}' は既に存在します。attribute-conditionを再適用します。"
  gcloud iam workload-identity-pools providers update-oidc "${WIF_PROVIDER_ID}" \
    --project="${PROJECT_ID}" \
    --location="global" \
    --workload-identity-pool="${WIF_POOL_ID}" \
    --attribute-condition="assertion.repository == '${GITHUB_REPOSITORY_SLUG}' && assertion.ref == 'refs/heads/main'"
else
  gcloud iam workload-identity-pools providers create-oidc "${WIF_PROVIDER_ID}" \
    --project="${PROJECT_ID}" \
    --location="global" \
    --workload-identity-pool="${WIF_POOL_ID}" \
    --display-name="GitHub Actions Provider" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-condition="assertion.repository == '${GITHUB_REPOSITORY_SLUG}' && assertion.ref == 'refs/heads/main'"
fi

echo "=== [4/7] CI/CD用サービスアカウント(冪等) ==="
if gcloud iam service-accounts describe "${DEPLOYER_SA}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "[OK] サービスアカウント '${DEPLOYER_SA}' は既に存在します(スキップ)。"
else
  gcloud iam service-accounts create "${DEPLOYER_SA_NAME}" \
    --project="${PROJECT_ID}" \
    --display-name="GitHub Actions Cloud Run Deployer"
fi

# WIF経由でこのサービスアカウントになりすます(impersonate)権限を、自リポジトリの
# OIDC subjectのみに限定して付与する(add-iam-policy-bindingはgcloud側で元々冪等)。
gcloud iam service-accounts add-iam-policy-binding "${DEPLOYER_SA}" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${WORKLOAD_IDENTITY_POOL_ID}/attribute.repository/${GITHUB_REPOSITORY_SLUG}"

echo "=== [5/7] CI/CD用サービスアカウントへの最小権限付与(冪等) ==="
for ROLE in \
  "roles/artifactregistry.writer" \
  "roles/run.admin" \
  "roles/iam.serviceAccountUser" \
  "roles/containeranalysis.occurrences.viewer"
do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOYER_SA}" \
    --role="${ROLE}" \
    --condition=None >/dev/null
done
echo "[OK] ${DEPLOYER_SA} へ最小権限セットを付与しました。"

echo "=== [6/7] Cloud Run実行サービスアカウントへの権限付与(冪等) ==="
# roles/secretmanager.secretAccessor はCloud Runの実行時サービスアカウントのみに
# 付与する(CI/CD用サービスアカウントには付与しない。デプロイ実行者への過剰な権限
# 付与を避ける、docs/DEPLOYMENT.mdと同じ方針)。roles/datastore.userはFirestore/
# Firebase Admin SDKをApplication Default Credentials経由で使うために必要
# (serviceAccountKey.jsonはCloud Run上では使わない、docs/DEPLOYMENT.md参照)。
for ROLE in "roles/secretmanager.secretAccessor" "roles/datastore.user"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="${ROLE}" \
    --condition=None >/dev/null
done
echo "[OK] ${RUNTIME_SA} へ実行時権限を付与しました。"

echo "=== [7/7] Secret Manager(GEMINI_API_KEY / ANTHROPIC_API_KEY) ==="
create_or_rotate_secret() {
  local secret_name="$1"
  if gcloud secrets describe "${secret_name}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    if [[ "${ROTATE_SECRETS}" != "1" ]]; then
      echo "[OK] シークレット '${secret_name}' は既に存在します(スキップ。ローテーションする場合は ROTATE_SECRETS=1 を付けて再実行)。"
      return
    fi
    echo "[INFO] '${secret_name}' の新しいバージョンを追加します(ROTATE_SECRETS=1)。"
    read -rsp "  ${secret_name} の新しい値を入力: " secret_value
    echo
    printf '%s' "${secret_value}" | gcloud secrets versions add "${secret_name}" --project="${PROJECT_ID}" --data-file=-
    unset secret_value
  else
    echo "[INFO] '${secret_name}' を新規作成します。"
    read -rsp "  ${secret_name} の値を入力: " secret_value
    echo
    printf '%s' "${secret_value}" | gcloud secrets create "${secret_name}" --project="${PROJECT_ID}" --data-file=-
    unset secret_value
  fi
}
create_or_rotate_secret "GEMINI_API_KEY"
create_or_rotate_secret "ANTHROPIC_API_KEY"

echo ""
echo "GitHub Secrets へ以下を登録してください(Settings -> Secrets and variables -> Actions):"
echo "  WIF_PROVIDER      = projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL_ID}/providers/${WIF_PROVIDER_ID}"
echo "  WIF_SERVICE_ACCOUNT = ${DEPLOYER_SA}"
echo ""
echo "サービスアカウントキーJSON(credentials.json等)はGitHub Secretsに一切登録しないこと"
echo "(WIFの目的そのものであり、登録してしまうとこの構成全体の意味が失われる)。"
echo ""
echo "セットアップ完了。動作確認は infra/docs/gcp_wif_artifact_registry_setup.md の"
echo "「動作確認」節に従うこと。"
