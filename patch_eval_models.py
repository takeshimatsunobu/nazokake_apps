import re

file_path = 'backend/main.py'
try:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. 必要なインポートの追加
    if 'from typing import Optional' not in content:
        content = 'from typing import Optional\n' + content

    # 2. Evaluate API (RM用: 真の人間評価フラグの追加)
    content = re.sub(
        r'("user_score":\s*req\.user_score\s*,)',
        r'\1\n                "is_synthetic": False,  # 🛑 RM用: 真の人間評価フラグ\n                "source": "human_web_ui",  # 🛑 RM用: 経路特定フラグ',
        content
    )

    # 3. HumanSubmitRequest モデル (DPO用: parent_id の追加)
    if 'parent_id: Optional[str]' not in content:
        content = re.sub(
            r'(class HumanSubmitRequest\(BaseModel\):[\s\S]*?nazokake_text:\s*str)',
            r'\1\n    parent_id: Optional[str] = None  # 🛑 DPO用: 修正元のAI作品ID',
            content
        )

    # 4. Submit Human API (SFT/DPO用: 血統フラグの保存)
    content = re.sub(
        r'("author":\s*"Human"\}?)',
        r'"author": "Human",\n            "parent_id": getattr(req, "parent_id", None),\n            "is_sft_data": True if getattr(req, "parent_id", None) else False}',
        content
    )

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
        
    print("✅ backend/main.py のパッチ適用に成功しました！")
except Exception as e:
    print(f"🚨 エラーが発生しました: {e}")
