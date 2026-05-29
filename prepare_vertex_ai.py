import json
import os

def convert_to_vertex_format():
    print('\n=========================================')
    print(' 🧠 Vertex AI (Gemini) 学習用データ変換 開始')
    print('=========================================\n')

    input_file = 'dataset_dpo_training.jsonl'
    output_file = 'gemini_sft_tuning_data.jsonl'

    if not os.path.exists(input_file):
        print(f'⚠️ {input_file} が見つかりません。先にエクスポートを実行してください。')
        return

    vertex_data = []
    
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            record = json.loads(line)
            
            # Vertex AI の Gemini SFTフォーマットに変換
            # AIに「こう聞かれたら（user）、こう返せ（model）」という理想の対話を定義します。
            # ※DPOデータのうち、人間が直した「大正解(chosen)」のみをSFTとして学習させます。
            vertex_record = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": record.get("prompt", "")}]
                    },
                    {
                        "role": "model",
                        "parts": [{"text": record.get("chosen", "")}]
                    }
                ]
            }
            vertex_data.append(vertex_record)

    if not vertex_data:
        print('⚠️ 変換するデータがありません。「編集して道場破り」を行ってデータを作成してください。')
        return

    with open(output_file, 'w', encoding='utf-8') as out_f:
        for item in vertex_data:
            out_f.write(json.dumps(item, ensure_ascii=False) + '\n')

    print(f'✅ Vertex AI 用フォーマット変換完了！: {len(vertex_data)} 件')
    print(f'📄 出力ファイル: {output_file}')
    print('\n💡 このファイルを Google Cloud コンソールから Vertex AI にアップロードすれば、')
    print('   Takeshiさんのセンスを学習した【Gemini v2 モデル】が誕生します！')
    print('=========================================\n')

if __name__ == '__main__':
    convert_to_vertex_format()
