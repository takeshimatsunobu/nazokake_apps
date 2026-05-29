import os
from google.cloud import firestore

# プロジェクトIDを明示的に指定
db = firestore.Client(project="nazokakeapp-137e5")

def initialize_config():
    config_ref = db.collection("system_config").document("evaluation_settings")
    
    # 学術的な初期設定
    settings = {
        "active_method": "Method_B",
        "methods": {
            "Method_A": "ロジカル思考（構造と因果関係を重視）",
            "Method_B": "クリエイティブ思考（飛躍と意外性を重視）",
            "Method_C": "情緒思考（共感とユーモアを重視）"
        },
        "prompts": {
            "create": "お題Aから連想される意外な単語Bを抽出し、それらを『詰まる』のような多義語で繋いだ謎掛けを作成せよ。",
            "evaluate": "以下の11指標に対し、学術的客観性を持って0.0-1.0で採点せよ。理由(reasoning)は日本語で出力せよ。"
        },
        "weights": {
            "S_sur": 1.2, "S_cm": 1.0, "S_rhy": 0.9, "S_nat": 1.0
        }
    }
    
    config_ref.set(settings)
    print("✅ Firestore: system_config/evaluation_settings を初期化したぞ！")

if __name__ == "__main__":
    initialize_config()
