"""
tools/deploy/check_deploy_status.py
======================================
検証VM(nazokake-l4-vm)のDoD(Definition of Done)検証を、gcloud compute ssh経由の
直接ログイン・コマンド実行無しに行うためのCLI(instructions/212)。

【背景】従来はデプロイ後、Agent(またはオペレーター)がgcloud compute sshで検証VM
へ直接ログインし、docker compose ps・SQLiteの行数確認等を都度実行していた
(tools/deploy/deploy_to_vm.ps1・gcloud_ssh_wrapper.ps1)。これはSRE監査により
「自律型Agentの過剰権限」と指摘され、代わりにVM側(infra/verification_env/
deploy_pull.sh)がデプロイ完了時にFirestoreへ自身の状態をpushし(outbound-only)、
このスクリプトはそのFirestore上の状態を読むだけでDoDを判定する(疎結合)。

使い方:
    uv run python tools/deploy/check_deploy_status.py --instance nazokake-l4-vm
    # デプロイ状態が存在しない、またはstatus!="deployed"の場合はsys.exit(1)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from nazokake_core.deploy_status_sync import read_deploy_status  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="検証VMのデプロイ状態をFirestore経由で確認する(SSH不要のDoD検証)"
    )
    parser.add_argument("--instance", default="nazokake-l4-vm", help="検証VMのインスタンス名")
    parser.add_argument(
        "--expect-commit",
        default=None,
        help="この短縮コミットハッシュがデプロイ済みであることを要求する(省略時は状態のみ確認)",
    )
    args = parser.parse_args()

    status = read_deploy_status(args.instance)
    if status is None:
        print(
            f"🚨 [DoD] '{args.instance}' のデプロイ状態がFirestoreに記録されていません"
            "(一度も正常デプロイが完了していない可能性があります)。",
            file=sys.stderr,
        )
        return 1

    print(f"[DoD] instance={args.instance}")
    print(f"      status={status.get('status')}")
    print(f"      commit_hash={status.get('commit_hash')}")
    print(f"      message={status.get('message')}")
    print(f"      containers={status.get('containers')}")
    print(f"      updated_at={status.get('updated_at')}")

    if status.get("status") != "deployed":
        print(f"🚨 [DoD] status='{status.get('status')}' は'deployed'ではありません。", file=sys.stderr)
        return 1

    if args.expect_commit and status.get("commit_hash") != args.expect_commit:
        print(
            f"🚨 [DoD] デプロイ済みcommit_hash='{status.get('commit_hash')}' が期待値"
            f"'{args.expect_commit}' と一致しません。",
            file=sys.stderr,
        )
        return 1

    print("✅ [DoD] 検証VMは期待される状態でデプロイ済みです。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
