import streamlit as st
import pandas as pd
from google.cloud import firestore

@st.cache_resource
def get_firestore_client():
    return firestore.Client()

@st.cache_data(ttl=300)
def fetch_evaluated_data():
    db = get_firestore_client()
    # status == 2 かつ 未評価のデータを取得
    query = db.collection("nazokake_items").where("status", "==", 2).where("FINAL_SCORE_HUMAN", "==", None).limit(500)
    
    docs = query.stream()
    data_list = []
    
    for doc in docs:
        item = doc.to_dict()
        item["id"] = doc.id
        
        # Firestoreのネストされた 'scores' マップを展開
        if "scores" in item and isinstance(item["scores"], dict):
            for k, v in item["scores"].items():
                item[k] = v
                
        if "reasoning" not in item:
            item["reasoning"] = "推論根拠データなし"
            
        data_list.append(item)
        
    # データが空の場合は空のDataFrameを返す
    return pd.DataFrame(data_list) if data_list else pd.DataFrame()

def save_human_evaluation(doc_id: str, score: float):
    db = get_firestore_client()
    db.collection("nazokake_items").document(doc_id).update({"FINAL_SCORE_HUMAN": score})
    fetch_evaluated_data.clear() # キャッシュクリアで最新化
    return True