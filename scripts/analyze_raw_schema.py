import json

def analyze_raw_data():
    print("\n================ [ ファクト確認: 生データのスキーマ解剖 ] ================")
    with open("data/raw_firestore_dump.json", "r", encoding="utf-8") as f:
        all_raw_data = json.load(f)
        
    for i, item in enumerate(all_raw_data[:3], 1):
        doc_id = item.get("id")
        raw_data = item.get("data", {})
        
        print(f"\n📄 [{i}/3] ドキュメントID: {doc_id}")
        print(f"🔑 存在するキーの一覧:")
        
        for key in raw_data.keys():
            val = raw_data[key]
            # 値の先頭30文字だけサンプルとして表示
            val_preview = str(val)[:30].replace("\n", " ")
            print(f"  - {key}: {val_preview}...")

if __name__ == "__main__":
    analyze_raw_data()
