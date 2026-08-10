"""
tools/check_instructions_layout.py
===================================
tools/instructions/ 配下に再発した「tools/instructions/tools/instructions/...」
ネスト(instructions/194で発覚、最大6階層・113ファイルが被害)を検知するFail-Closed
ガード(instructions/194)。

【調査済みの根本原因】このネストは、tools/compile_knowledge.py・tools/nazo_agent.py・
tools/agent_graph.py等、tools/instructions/を扱う既存のPythonコードのバグではない
(いずれもBASE_DIR = Path(__file__).resolve().parent.parentから絶対パスで正しく
アンカーしている)。実際の原因は、対話シェルセッション(Bashツールはセッション内で
作業ディレクトリが持続する)で一度 tools/instructions/ へ`cd`した状態が復元されず、
その後の新規指示書作成コマンドが相対パス "tools/instructions/NNN_....txt" で
書き込まれ、ネスト済みのcwdからさらに1階層深く着地した、という運用上のミスが
セッションを跨いで複利的に積み重なったものである。よって修正はコードの書き換え
ではなく、再発を確実に検知するこの静的ガードと、既存ネストの平坦化(git mv)の
組み合わせとなる。

使い方:
    uv run python tools/check_instructions_layout.py
    # ネストなし: sys.exit(0)
    # ネストを検知: 該当パスを列挙してsys.exit(1)(Fail-Closed)
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
# 【フェーズ2の構造整理で移設】tools/instructions/ は本番デプロイに不要な履歴文書
# (instructions/NNNとしてコードベース全体のコメントから無数に参照される意思決定
# トレイル)のため archive/instructions_history/tools_instructions/ へ隔離した。
# このガード自体は instructions/194 の再発防止(6階層・113ファイルのネスト事故)
# として引き続き必要なため、移設後の実際の置き場を追いかけて更新する
# (旧パスのままだと INSTRUCTIONS_DIR.is_dir() が常に False になり、チェックが
# 気付かれないまま永久に無効化されてしまう)。
INSTRUCTIONS_DIR = BASE_DIR / "archive" / "instructions_history" / "tools_instructions"


def find_nested_instructions(instructions_dir: Path) -> list[Path]:
    """instructions_dir配下で、ルート直下を超えて"tools"セグメントを含むパス
    (=誤って積み重なったネスト)を全て返す。

    ネストは常に"tools/instructions"の対で発生するとは限らず、
    "tools/instructions/tools/104_....txt"のように"instructions"を伴わない
    単独の"tools"セグメント1段だけのケースも実在するため、"instructions"との
    共存は条件にしない("tools"セグメント単独の出現だけで十分に異常)。
    """
    offenders = []
    for path in instructions_dir.rglob("*"):
        relative_parts = path.relative_to(instructions_dir).parts
        if "tools" in relative_parts:
            offenders.append(path)
    return offenders


def main() -> int:
    if not INSTRUCTIONS_DIR.is_dir():
        print(f"✅ [check_instructions_layout] {INSTRUCTIONS_DIR} が存在しません(チェック対象なし)。")
        return 0

    offenders = find_nested_instructions(INSTRUCTIONS_DIR)
    if offenders:
        print(
            "🚨 [Fail-Closed] tools/instructions/ 配下に異常なネスト "
            f"(tools/instructions/tools/instructions/...) を検知しました({len(offenders)}件)。"
            "instructions/194の根本原因(シェルの作業ディレクトリが持続するセッションで"
            "相対パスから指示書を作成した)が再発しています。以下のパスを"
            "tools/instructions/直下へ `git mv` で移動してください:",
            file=sys.stderr,
        )
        for offender in sorted(offenders):
            print(f"  - {offender.relative_to(BASE_DIR)}", file=sys.stderr)
        return 1

    print(f"✅ [check_instructions_layout] {INSTRUCTIONS_DIR} にネストは検知されませんでした。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
