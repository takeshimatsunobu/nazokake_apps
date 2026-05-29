import firebase_admin
from firebase_admin import credentials, firestore
import json
import statistics

def investigate_and_export():
    print('\n=========================================')
    print(' 🕵️‍♂️ データベース緊急監査 ＆ クリーン抽出開始')
    print('=========================================\n')
    
    try:
        cred = credentials.Certificate('serviceAccountKey.json')
        firebase_admin.initialize_app(cred)
    except ValueError:
        pass

    db = firestore.client()
    
    # 曖昧なクエリを避け、全データを確実にPython側で検証する
    docs = db.collection('nazokake_items').stream()
    
    export_data = []
    ghost_samples = []
    valid_count = 0
    ghost_count = 0
    
    for doc in docs:
        data = doc.to_dict()
        evals = data.get('user_evaluations', [])
        
        # 配列が存在しない、または空の場合はスキップ
        if not evals or not isinstance(evals, list):
            continue
            
        valid_scores = []
        for e in evals:
            # 辞書型であること、かつキーが存在することを厳密にチェック
            if isinstance(e, dict):
                score = e.get('user_score') or e.get('rating')
                # スコアが数値であり、1〜5の間である「真の人間評価」のみを抽出
                if isinstance(score, (int, float)) and 1 <= score <= 5:
                    valid_scores.append(score)
        
        if valid_scores:
            # 真のデータ
            avg_score = statistics.mean(valid_scores)
            record = {
                "input_text": data.get('nazokake_text', ''),
                "ai_self_scores": data.get('scores', {}), 
                "human_reward_score": round(avg_score, 2), 
                "eval_count": len(valid_scores)
            }
            export_data.append(record)
            valid_count += 1
        else:
            # user_evaluations配列はあるが、有効なスコアが入っていない「Ghostデータ」
            ghost_count += 1
            if len(ghost_samples) < 3:  # 原因究明のために3件だけサンプルを確保
                ghost_samples.append({
                    "doc_id": doc.id,
                    "A_TITLE": data.get("A_TITLE", ""),
                    "user_evaluations": evals
                })

    # クリーンなデータだけをJSONLで保存
    output_file = 'reward_model_dataset_strict.jsonl'
    with open(output_file, 'w', encoding='utf-8') as f:
        for item in export_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')

    print('=========================================')
    print(' 🚨 データベース監査結果 🚨')
    print('=========================================')
    print(f'✅ 真の人間評価データ (星1〜5) : {valid_count} 件')
    print(f'👻 偽装/エラーデータ (Ghost) : {ghost_count} 件')
    
    if ghost_samples:
        print('\n【🕵️‍♂️ Ghostデータの中身（犯人の正体）】')
        for g in ghost_samples:
            print(json.dumps(g, ensure_ascii=False, indent=2))
            
    print(f'\n📄 クリーンなデータだけを [{output_file}] に再出力しました！')
    print('=========================================\n')

if __name__ == '__main__':
    investigate_and_export()
