"""data-sync-daemon の起動エントリポイント(instructions/001)。

SSoT_architecture.md 8.2節が定義するFirestore<->ローカルSQLiteの非同期バック
アップ同期(workers/配下)は、本リポジトリの現時点ではまだ実装されていない
(SSoT 7節のActive Backlogにも未着手として記載が無い、純粋な仕様のみの状態)。
このスクリプトは同期ロジックを偽装・先取り実装せず、コンテナが正常に起動・
待機できることのみを保証するプレースホルダーとして、その旨をログに明示する。
"""

import sys
import time

SYNC_INTERVAL_SECONDS = 300


def main() -> None:
    print(
        "[data-sync-daemon] Firestore<->SQLite同期ワーカーは未実装です"
        "(SSoT_architecture.md 8.2節は仕様のみ)。"
        "コンテナ・マウント構成の検証用プレースホルダーとして待機します。",
        file=sys.stderr,
        flush=True,
    )
    while True:
        time.sleep(SYNC_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
