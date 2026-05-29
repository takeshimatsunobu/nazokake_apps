import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

def purge_synthetic_data():
    print('\n🔥 【大パージ作戦】開始 🔥')
    
    try:
        cred = credentials.Certificate('serviceAccountKey.json')
        firebase_admin.initialize_app(cred)
    except ValueError:
        pass

    db = firestore.client()
    
    # 評価データを持っているドキュメントを全件取得
    docs = db.collection('nazokake_items').where(filter=FieldFilter('user_evaluations', '!=', [])).stream()
    
    purged_docs_count = 0
    deleted_evals_count = 0
    kept_human_evals_count = 0
    
    for doc in docs:
        data = doc.to_dict()
        evals = data.get('user_evaluations', [])
        original_len = len(evals)
        
        # 💡 外科手術: is_synthetic が True のものを配列から削ぎ落とす
        human_only_evals = [
            e for e in evals 
            if isinstance(e, dict) and e.get('is_synthetic') is not True
        ]
        
        # もしダミーデータが含まれていて、配列の中身に変化があった場合のみDBを更新
        if len(human_only_evals) != original_len:
            db.collection('nazokake_items').document(doc.id).update({
                'user_evaluations': human_only_evals
            })
            purged_docs_count += 1
            deleted_evals_count += (original_len - len(human_only_evals))
        
        kept_human_evals_count += len(human_only_evals)

    print('\n=========================================')
    print(' ✨ データベースの浄化（パージ）が完了しました！ ✨')
    print('=========================================')
    print(f'🗑️ 除去したAIダミー評価 (Ghost) : {deleted_evals_count} 件')
    print(f'💎 残された真の人間評価 (Human) : {kept_human_evals_count} 件')
    print(f'📄 更新されたドキュメント数       : {purged_docs_count} 件')
    print('=========================================\n')
    print('💡 これでデータベースは「本物のデータのみ」になりました！')

if __name__ == '__main__':
    purge_synthetic_data()
