# firestore_db.py
import firebase_admin
from firebase_admin import credentials, firestore
import datetime
import json

def initialize_firestore():
    """Firestoreの初期化"""
    if not firebase_admin._apps:
        # ※実際のサービスアカウントキーのパスに置き換えて使用します
        try:
            cred = credentials.Certificate(".firebase/serviceAccountKey.json")
            firebase_admin.initialize_app(cred)
        except Exception as e:
            print(f"⚠️ Firestore初期化警告（ローカルテスト用）: {e}")
    return firestore.client()

def save_evaluation_result(doc_id, theme, nazokake_text, ai_evaluation_json_str):
    """
    AIの11軸評価結果と、人間の評価枠を分離してFirestoreに保存する
    """
    db = initialize_firestore()
    doc_ref = db.collection("nazokake_evaluations").document(doc_id)

    # AIが返したJSON文字列を辞書型に変換
    try:
        ai_data = json.loads(ai_evaluation_json_str)
    except json.JSONDecodeError:
        print("🚨 AIのJSON出力パースに失敗しました")
        ai_data = {}

    # Firestoreへ保存するデータ構造の構築
    save_data = {
        "theme": theme,
        "nazokake_text": nazokake_text,
        # AIによる評価データ（11軸）
        "ai_total_score": ai_data.get("ai_total_score", 0),
        "evaluation_details": ai_data.get("evaluation_details", {}),
        "judge_comment": ai_data.get("judge_comment", ""),
        # 人間による評価データ（完全に分離・初期状態はnullまたは0）
        "human_score": None, 
        "human_likes": 0,
        "created_at": firestore.SERVER_TIMESTAMP
    }

    # データの保存（マージ）
    doc_ref.set(save_data, merge=True)
    print(f"✅ Firestoreへの保存が完了しました。 [DocID: {doc_id}]")

if __name__ == "__main__":
    # テスト用モックデータ
    mock_json = """
    {
        "ai_total_score": 92,
        "evaluation_details": {
            "S_nat": 9, "S_tech": 10, "S_rhy": 8, "S_prosody": 8,
            "S_sur": 9, "S_emo": 9, "S_cultural": 10, "S_visual": 8,
            "S_sensory": 7, "S_cm": 6, "S_ontology": 8
        },
        "judge_comment": "テスト講評です。"
    }
    """
    save_evaluation_result("test_doc_001", "満員電車", "「満員電車」とかけて「寿司屋」と解く。その心は、どちらも「にぎり」が付き物です。", mock_json)
