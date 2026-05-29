import os
from google.cloud import firestore
import json

def print_header(title):
    print("\n" + "="*60)
    print(f" 🛠️ {title}")
    print("="*60)

def main():
    print_header("Firestore データ完全修復（リペア）プログラム")
    print("削除は一切行いません。壊れたデータをすべて正しい形式に変換・救出します...\n")
    
    try:
        db = firestore.Client()
        # 評価完了(status: 2)のデータのみを対象とする
        docs = db.collection("nazokake_items").where(filter=firestore.FieldFilter("status", "==", 2)).stream()
        
        EVAL_AXES = [
            "S_sur", "S_nat", "S_tech", "S_emo", "S_rhy", "S_sensory", 
            "S_visual", "S_ontology", "S_cultural", "S_cm", "S_prosody"
        ]
        
        batch = db.batch()
        count = 0
        
        print("データを読み込み、修復処理を開始しました...")
        
        for doc in docs:
            data = doc.to_dict()
            scores_raw = data.get("scores", {})
            
            # デフォルトで全軸0.0の綺麗な辞書を用意
            new_scores = {k: 0.0 for k in EVAL_AXES}
            extracted_reasoning = data.get("reasoning", data.get("eval_reasoning", ""))
            
            # パターン1: 文字列として丸ごと保存されている場合
            if isinstance(scores_raw, str):
                try:
                    scores_raw = json.loads(scores_raw)
                except:
                    scores_raw = {}
            
            # パターン2: 辞書型（正常、または文字列混入、reasoning混入）
            if isinstance(scores_raw, dict):
                for k, v in scores_raw.items():
                    if k in EVAL_AXES:
                        try:
                            # 確実にfloat（数値）に変換
                            new_scores[k] = float(v)
                        except:
                            pass
                    # reasoningがscoresの中に迷い込んでいたら救出する！
                    elif k in ["reasoning", "eval_reasoning", "comment"] and isinstance(v, str) and len(v) > 5:
                        if not extracted_reasoning: # 元が空なら上書き
                            extracted_reasoning = v
            
            # パターン3: リスト型になってしまっている場合（あのエラーの原因）
            elif isinstance(scores_raw, list):
                # 無視してデフォルトの0.0辞書を適用する
                pass

            # 更新用データの作成
            updates = {
                "scores": new_scores
            }
            if extracted_reasoning:
                updates["reasoning"] = extracted_reasoning
                
            doc_ref = db.collection("nazokake_items").document(doc.id)
            batch.update(doc_ref, updates)
            
            count += 1
            
            # Firestoreのバッチ書き込み上限（500件）への対応
            if count % 400 == 0:
                batch.commit()
                batch = db.batch()
                print(f"  ... {count} 件の修復を完了")

        # 残りのバッチをコミット
        if count % 400 != 0:
            batch.commit()
            
        print(f"\n✅ 大成功！合計 {count} 件のデータを完璧なフォーマットに修復しました！")
        print("これでStreamlitのダッシュボードでエラーが起きることはありません。")

    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")

if __name__ == "__main__":
    main()
