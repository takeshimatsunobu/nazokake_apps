import csv
from pathlib import Path

files = [
    "041世界の言語活動調査.(学術的).csv",
    "042 世界の言語活動調査(実態調査).csv"
]

for file_name in files:
    p = Path(file_name)
    print(f"\n=== {file_name} ===")
    if not p.exists():
        print("❌ ファイルが見つかりません。")
        continue
        
    for enc in ['cp932', 'utf-8-sig', 'utf-8']:
        try:
            with open(p, 'r', encoding=enc) as f:
                reader = csv.reader(f)
                next(reader)
                rows = list(reader)
                print(f"✅ {enc}: {len(rows)} 行読み込み成功")
                break
        except Exception as e:
            print(f"⚠️ {enc} エラー: {type(e).__name__} - {e}")
            