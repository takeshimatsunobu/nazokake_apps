# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path

try:
    from jinja2 import Template
except ImportError:
    print("Error: jinja2 is not installed. Please run: uv run --with jinja2 python tools/generate_architecture_doc.py")
    sys.exit(1)

# 出力先ディレクトリの確保
Path('docs').mkdir(parents=True, exist_ok=True)

template_str = """# {{ title }}

## 1. はじめに (Introduction)
{{ intro }}

## 2. システム全体の仕組み (Big Picture)
{{ big_picture_desc }}

```mermaid
graph TD
    User[ユーザーからの依頼] --> Gemma[Gemma: 下ごしらえ]
    Gemma --> Qwen[Qwen: 本格調理・組み立て]
    Qwen --> Claude[Claude: 最終チェック・品質管理]
    Claude --> Gatekeeper[AST検品ゲート]
    Gatekeeper -- 合格 --> Disk[金庫へ保存]
    Gatekeeper -- 不合格 --> Claude
3. 3つのAIキャラクターと役割 (Escalation Pipeline)
{{ cascade_desc }}
{% for ai in ai_roles %}

{{ ai.name }} ({{ ai.metaphor }}): {{ ai.desc }}
{% endfor %}

4. 安全を守る門番たち (Security & SRE)
{{ security_desc }}
{% for sec in security_features %}

{{ sec.name }} ({{ sec.metaphor }}): {{ sec.desc }}
{% endfor %}

5. 経験を食べて成長する仕組み (Data Flywheel)
{{ flywheel_desc }}
{% for feature in flywheel_features %}

{{ feature.name }}: {{ feature.desc }}
{% endfor %}
"""

data = {
"title": "Nazo-Agent アーキテクチャ解説（初学者向け）",
"intro": "Nazo-Agentは、SRE（サイト信頼性エンジニアリング）のプラクティスを導入した自律型のAIエージェントです。このドキュメントでは、複数のAIが連携してどのようにコードを書き換え、安全にシステムを運用しているのかを、現実世界の具体的なアナロジーを用いて解説します。",
"big_picture_desc": "システムは「レストランの厨房」に例えることができます。ユーザーからの依頼を受け取ると、複数のAIが役割分担して料理（コード）を作成し、最後に厳しい検品ゲート（構文チェック）と安全な保存（金庫）を経て提供されます。",
"cascade_desc": "システムは、3つのAIがそれぞれの得意分野を活かして連携する「エスカレーション・パイプライン」を採用しています（LLMカスケード）。",
"ai_roles": [
{"name": "Gemma", "metaphor": "見習いシェフ", "desc": "素早く動けるのが特徴です。大量のログや単純なデータから必要な情報を抽出し、「下ごしらえ」を担当します。"},
{"name": "Qwen", "metaphor": "メインシェフ", "desc": "賢くバランスの取れたAIです。Gemmaが用意した材料を元に、プログラムの論理や組み立てなど、開発における「本格的な調理」の大部分を担当します。"},
{"name": "Claude", "metaphor": "総料理長", "desc": "最も高度な推論力を持つAIです。複雑な問題の解決や、最終的な品質チェック、エラー発生時の軌道修正を担当します。"}
],
"security_desc": "AIがコードを直接書き換えるのは、間違えたときにシステムを破壊するリスクが伴います。そのため、厳格な「検品ゲート」と「金庫」の仕組みを用意しています。",
"security_features": [
{"name": "AST検品ゲート", "metaphor": "出荷前の検品ゲート", "desc": "AIが書いたコードをシステムに反映する前に、文法が正しいかをプログラム的に検査します。料理に異物が混入していないかを機械的にチェックする工程です。"},
{"name": "アトミック書き込み", "metaphor": "金庫への格納", "desc": "保存中にシステムが停止してもファイルが壊れないよう、一時ファイルを作ってから一瞬で本番ファイルとすり替える（不可分な置換）仕組みです。"}
],
"flywheel_desc": "Nazo-Agentは一度作って終わりではなく、AI自身が経験から学習し、継続的に賢くなる仕組み（Data Flywheel）を備えています。",
"flywheel_features": [
{"name": "Best-of-N", "desc": "複数の回答候補を出し、最も品質の良いものを選択する手法です。"},
{"name": "DPO (直接選好最適化)", "desc": "「どの回答が良くて、どれが悪かったか」というフィードバックログをAIの学習データとして蓄積し、モデル自体を継続的に成長させる仕組みです。"}
]
}

out = Path('docs/architecture_for_beginners.md')
out.write_text(Template(template_str).render(data), encoding='utf-8')
print(f'Done! Generated {out} successfully.')
