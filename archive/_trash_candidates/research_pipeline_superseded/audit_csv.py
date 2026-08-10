import csv
from pathlib import Path
import sys

csv_path = Path("022 なぞかけその他の研究の現状.csv")

if not csv_path.exists():
    print(f"❌ ファイルが見つかりません: {csv_path}")
    sys.exit(1)

print(f"🔍 {csv_path.name} のスキーマ解析を開始します...")

encodings = ['utf-8-sig', 'cp932', 'euc-jp']
success = False

for enc in encodings:
    try:
        with open(csv_path, 'r', encoding=enc) as f:
            reader = csv.reader(f)
            header = next(reader)
            print(f"\n✅ [HEADER] カラム数: {len(header)} (エンコーディング: {enc})")
            for i, col in enumerate(header):
                print(f"  Col {i}: {col}")
            
            first_row = next(reader)
            print(f"\n✅ [FIRST ROW DATA]")
            for i, val in enumerate(first_row):
                preview = val[:60].replace('\n', '\\n') + ('...' if len(val) > 60 else '')
                print(f"  Col {i}: {preview}")
        success = True
        break
    except UnicodeDecodeError:
        continue
    except Exception as e:
        print(f"❌ エラー ({enc}): {e}")
        sys.exit(1)

if not success:
    print("❌ すべてのエンコーディングでの読み込みに失敗しました。")
    sys.exit(1)
