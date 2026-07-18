"""
tools/ast_modifier.py
======================
Nazo-Agent ローカルファースト化(Epic 1) / Feature 1.2:
LLMによる非決定的な全文書き換え(Aiderへの過剰依存)を廃し、libcstによる
ASTベースの安全なピンポイント置換(関数/クラス単位)を行う基礎エンジン。

libcstはコメント・空白・インデント等の具象構文情報を保持したまま構文木を
編集できるため、対象外のコード(前後の関数・import・モジュールレベルの
コメント等)を一切破壊せずに、指定した関数/クラスのノードだけを新しい
コードで置き換えられる。

修正指示はJSON形式で受け取る:
{
    "file_path": "apps/evaluator/backend/main.py",
    "target_name": "health_check",
    "new_code": "async def health_check():\n    return {\"status\": \"ok\"}\n"
}
"""

import ast
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Literal

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import filelock
import libcst as cst
from pydantic import BaseModel, Field, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

FILE_LOCK_TIMEOUT_SEC = 10


class AstModificationInstruction(BaseModel):
    """修正指示の厳格なスキーマ。Claude API の Tool Calling(構造化出力)でも
    このモデルと同一の入力スキーマ(model_json_schema())を用いることで、
    APIレベルで型を保証する(Single Source of Truth)。"""

    file_path: str = Field(..., description="修正対象ファイルのパス")
    target_name: str = Field(..., description="置換対象の関数名またはクラス名(完全一致)")
    new_code: str = Field(..., description="置換後の関数/クラス定義の完全なソースコード")
    triage_type: Literal["bug_fix", "test_update"] = Field(
        default="bug_fix", description="バグ修正か、陳腐化したテストの更新か"
    )
    # CTOエスカレーション(tools/agent_graph.py)用の自己評価フィールド。デフォルト値は
    # 「不確実性の申告なし」を表す安全側の値であり、ast_modifier.py自身の適用ロジック
    # (apply_modification)はこれらの値を一切参照しない(Qwenの出力自己評価と、
    # 実際にAST置換を適用できるかどうかの構文的検証は独立した関心事のため)。
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="この修正案に対するモデル自身の確信度(0.0=全く自信がない〜1.0=完全に確信)",
    )
    requires_escalation: bool = Field(
        default=False,
        description="Trueの場合、この修正案は上位モデル(CTOノード)によるレビューが必要",
    )


class TargetNodeReplacer(cst.CSTTransformer):
    """target_nameに完全一致する関数/クラス定義ノードのみを、new_nodeに
    差し替えるTransformer。

    それ以外のノード(前後の関数・import・モジュールレベルのコメント等)には
    一切触れない。同名ノードが複数存在する場合は最初に見つかった1件のみを
    置換する(意図しない全置換を避けるため)。
    """

    def __init__(self, target_name: str, new_node: cst.CSTNode) -> None:
        self.target_name = target_name
        self.new_node = new_node
        self.replaced = False

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.BaseStatement:
        if self.replaced or original_node.name.value != self.target_name:
            return updated_node
        if not isinstance(self.new_node, cst.FunctionDef):
            return updated_node
        self.replaced = True
        # 直前の空行数・アタッチされたコメント行(leading_lines)は元ノードのものを
        # 引き継ぎ、置換によって前後の余白構造が変化しないようにする。
        return self.new_node.with_changes(leading_lines=original_node.leading_lines)

    def leave_ClassDef(
        self, original_node: cst.ClassDef, updated_node: cst.ClassDef
    ) -> cst.BaseStatement:
        if self.replaced or original_node.name.value != self.target_name:
            return updated_node
        if not isinstance(self.new_node, cst.ClassDef):
            return updated_node
        self.replaced = True
        return self.new_node.with_changes(leading_lines=original_node.leading_lines)


def _get_top_level_names(code_str: str) -> set[str]:
    """ソース全体をASTでパースし、トップレベルの関数/クラス/import/定数の
    識別子名の集合を返す。

    行数ヒューリスティック(is_mass_deletion等)は「行数を維持したまま無関係な
    コード要素を消し去る」ケースを検知できない。この関数はノード単位の名前集合を
    比較するためのセマンティック差分の基礎データを提供する。
    """
    tree = ast.parse(code_str)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Import):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Assign):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
    return names


@retry(
    retry=retry_if_exception_type(filelock.Timeout),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _atomic_write_text(path: Path, content: str) -> None:
    """対象ファイルを不可分(アトミック)に上書きする。

    対象ファイルと同一ディレクトリ(同一ドライブ・パーティション)に一時ファイルを
    作成して書き込み、fsyncで物理ディスクへ確実に同期した後、os.replaceで元ファイルを
    すげ替える。os.replaceはOS側で不可分な操作として保証されるため、書き込み中に
    プロセスが強制終了(OOM等)しても、対象ファイルが空(0バイト)や中途半端な内容の
    まま残ることはない(残るのは書き込み前の旧内容か、書き込み後の新内容のみ)。

    書き込み~すげ替えの一連の操作は `f"{path}.lock"` に対するファイルロック
    (filelock, タイムアウト付き)で保護し、複数プロセス/スレッドからの同時書き込みを
    排他制御する。タイムアウト(規定10秒)以内にロックを獲得できない場合、
    複数ワーカーからの一過性の競合を即座のフェイルファストにしないため、
    tenacityによる指数的バックオフ(1,2,4,8,10秒...最大5回試行)で再試行する。
    5回試行してもなお獲得できない場合のみ、filelock.Timeout が最終的に伝播する。

    トランザクション(ロック区間)を抜けた直後、ロックファイル自身
    (`f"{path}.lock"`)を物理的に破棄する。filelockはロック解放後もこの
    ファイル自体を残すため、放置するとDockerサンドボックス側のBlast Radius検知
    (Epic 2 5次元評価ゲート、instructions/158)が意図した書き込み対象以外の
    ファイル変更として誤検知(偽陽性)する。書き込み自体が失敗した場合でも
    ロックファイルだけは残さないよう、finallyで確実に破棄する。
    """
    lock_path = Path(f"{path}.lock")
    lock = filelock.FileLock(str(lock_path), timeout=FILE_LOCK_TIMEOUT_SEC)
    try:
        with lock:
            dir_name = os.path.dirname(str(path)) or "."
            tmp = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", errors="strict", dir=dir_name, delete=False
            )
            tmp_path = Path(tmp.name)
            try:
                tmp.write(content)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp.close()
                if path.exists():
                    # copystatはパーミッションに加えmtime/atime等のメタデータも
                    # 一時ファイルへ引き継ぐ(copymodeの上位互換)。
                    shutil.copystat(path, tmp_path)
                os.replace(tmp_path, path)
            except Exception:
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise
    finally:
        lock_path.unlink(missing_ok=True)


def _parse_new_node(new_code: str) -> cst.CSTNode:
    """new_code(関数/クラス定義1個ぶんのソース断片)をパースし、
    先頭の関数/クラス定義ノードを取り出す。"""
    module = cst.parse_module(new_code)
    for statement in module.body:
        if isinstance(statement, (cst.FunctionDef, cst.ClassDef)):
            return statement
    raise ValueError("new_code内に関数またはクラス定義が見つかりません。")


def apply_modification(instruction: dict) -> str:
    """1件の修正指示を適用し、結果メッセージを返す(ファイルは成功時のみ上書き)。"""
    try:
        validated = AstModificationInstruction(**instruction)
    except ValidationError as e:
        # フェイルファスト: LLM側の自己修正ループ(呼び出し元)にエラー内容をそのまま
        # 返し、再生成を促す。ここで正規表現等による救済・推測は一切行わない。
        return f"Error: instructionのバリデーションに失敗しました: {e}"

    file_path = validated.file_path
    target_name = validated.target_name
    new_code = validated.new_code

    if not file_path or not target_name or not new_code:
        return "Error: file_path, target_name, new_code はすべて必須です。"

    path = Path(file_path)
    if not path.exists():
        return f"Error: ファイル '{file_path}' が見つかりません。"

    try:
        new_node = _parse_new_node(new_code)
    except Exception as e:
        return f"Error: new_codeのパースに失敗しました: {e}"

    source = path.read_text(encoding="utf-8-sig", errors="strict")
    try:
        module = cst.parse_module(source)
    except Exception as e:
        return f"Error: 対象ファイルのパースに失敗しました: {e}"

    transformer = TargetNodeReplacer(target_name, new_node)
    modified_module = module.visit(transformer)

    if not transformer.replaced:
        return f"Error: 関数/クラス '{target_name}' が '{file_path}' 内に見つかりませんでした。"

    # 多段バリデーションゲート: libcstによる置換後の完全なコードが構文的に妥当か、
    # 書き込み直前に ast.parse で最終確認する。LLMのハルシネーションで生成された
    # new_code が個別には解釈できても、置換後の全体が壊れているケースを検知する
    # 最後の防波堤(破壊防御)。
    try:
        ast.parse(modified_module.code)
    except SyntaxError as e:
        print(f"[Fatal] 置換後のコードに構文エラーが存在するため、書き込みを中止します: {e}")
        sys.exit(1)

    # セマンティック差分検証(Semantic Diff): 行数ヒューリスティックでは検知できない
    # 「行数を維持したまま無関係な関数/クラスを消し去る」論理破壊を、ASTノード単位の
    # トップレベル名集合の比較で検知する。target_name以外の既存の関数/クラスが
    # 置換後に1つでも失われていれば、書き込みを中止する。
    try:
        original_names = _get_top_level_names(source)
        modified_names = _get_top_level_names(modified_module.code)
    except SyntaxError as e:
        print(f"[Fatal] セマンティック差分検証のためのASTパースに失敗しました: {e}")
        sys.exit(1)

    lost_names = (original_names - {target_name}) - modified_names
    if lost_names:
        print(
            "[Fatal] 無関係なコード要素（関数/クラス/インポート/定数）の消失を検知したため、"
            f"書き込みを中止します: {sorted(lost_names)}"
        )
        sys.exit(1)

    # 差分検閲(Diff Review): コンパイルは通るが論理が崩壊するタイプの事故
    # (「...」や空のpassによる大量削除、逆に暴走した大量挿入)をヒューリスティックで検知する。
    original_lines = len(source.splitlines())
    modified_lines = len(modified_module.code.splitlines())
    is_mass_deletion = original_lines > 20 and modified_lines < original_lines * 0.6
    is_mass_insertion = modified_lines > original_lines + 200
    if is_mass_deletion or is_mass_insertion:
        print(
            f"[Warning] 差分が極端すぎるため(元: {original_lines}行 -> 新: {modified_lines}行)、"
            "安全のため置換をブロックします"
        )
        sys.exit(1)

    _atomic_write_text(path, modified_module.code)
    return f"✅ '{target_name}' を '{file_path}' 内で安全に置換しました。"


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python tools/ast_modifier.py <instruction.json>")
        sys.exit(1)

    instruction_path = Path(sys.argv[1])
    if not instruction_path.exists():
        print(f"Error: 指示ファイル '{instruction_path}' が見つかりません。")
        sys.exit(1)

    instruction = json.loads(instruction_path.read_text(encoding="utf-8", errors="strict"))
    result = apply_modification(instruction)
    print(result)
    if result.startswith("Error:"):
        sys.exit(1)


if __name__ == "__main__":
    main()
