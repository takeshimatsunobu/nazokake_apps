"""nazokake-l4-vm 上で稼働するGPUアイドル監視・コスト保護シャットダウンスクリプト。
実体は /home/takes/nazokake-evaluator/scripts/auto_shutdown.py としてVM上にデプロイされる
(instructions/199で初めてバージョン管理下に置いた。それ以前はVM上の手編集のみで管理されていた)。
"""
import subprocess
import os
import fcntl

STATE_FILE = '/tmp/gpu_idle_minutes'
IDLE_LIMIT = 30  # 30分間GPU使用率0%でシャットダウン

DEPLOY_LOCK_FILE = '/tmp/deployment_in_progress.lock'


def get_gpu_utilization():
    try:
        # nvidia-smiからGPU使用率を取得
        res = subprocess.check_output(
            ['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits']
        )
        return int(res.decode().strip())
    except Exception:
        # 取得エラー時は安全のためシャットダウンを保留
        return 100


def is_deploy_in_progress():
    """デプロイスクリプト(deploy_pull.sh)が保持するflockを非ブロッキングで確認する。
    ロックを取得できた場合はデプロイプロセスが存在しない(=既に終了/クラッシュ済み)と
    判断し、直ちに解放してFalseを返す(mtimeベースの経過時間判定は行わない)。
    """
    if not os.path.exists(DEPLOY_LOCK_FILE):
        return False
    try:
        with open(DEPLOY_LOCK_FILE, 'r') as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                return False
            except OSError:
                # ロック取得できない = デプロイプロセスが現にロックを保持中
                return True
    except OSError:
        return False


def main():
    if is_deploy_in_progress():
        print("🔒 デプロイ進行中のロックを検知。シャットダウン監視を保留し、アイドルカウントをリセットします。")
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        return

    utilization = get_gpu_utilization()

    if utilization > 0:
        # GPUが使われていればカウントリセット
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
    else:
        # GPU使用率が0%の場合、カウントを進める
        count = 0
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                content = f.read().strip()
                count = int(content) if content.isdigit() else 0

        count += 1

        if count >= IDLE_LIMIT:
            print(f"🛑 {IDLE_LIMIT}分間のアイドルを検知。システムをシャットダウンします。")
            os.system('sudo shutdown -h now')
        else:
            with open(STATE_FILE, 'w') as f:
                f.write(str(count))


if __name__ == '__main__':
    main()
