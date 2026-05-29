import os
import time
from dotenv import load_dotenv, find_dotenv
from google import genai
from google.genai import types

# .envからAPIキーを読み込む
load_dotenv(find_dotenv())

def print_header(title):
    print("\n" + "="*50)
    print(f" {title}")
    print("="*50)

def main():
    print_header("謎掛け学術振興会 - データ循環シミュレーター (CUI版)")
    print("このツールは、人間のフィードバックからAIが自己進化する過程をシミュレーションします。")
    print("AIのモデルは 'gemini-3-flash-preview' を使用します。\n")

    # APIキーの確認
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("🚨 エラー: ルートディレクトリの.envから GEMINI_API_KEY を読み込めませんでした。")
        return
    client = genai.Client(api_key=api_key)

    # 1. パラメータの設定
    print("[1] ユーザーの評価傾向を選択してください:")
    print("  1: 的確な高評価 (AIも人間も面白いと判断)")
    print("  2: 正当な低評価 (AIは0点、人間は1点で共に低評価。例：富士山)")
    print("  3: いたずら・荒らし (AIは高得点だが、人間は意味不明な理由で星1をつける)")
    
    while True:
        try:
            user_behavior = int(input("選択 (1-3) > "))
            if user_behavior in [1, 2, 3]:
                break
            print("1から3の数字を入力してください。")
        except ValueError:
            print("無効な入力です。")

    print("\n[2] AI自己反省時のTemperature (創造性/ブレの度合い) を設定してください (例: 0.4):")
    while True:
        try:
            temp_input = input("Temperature (デフォルト 0.4) > ")
            if temp_input == "":
                temperature = 0.4
                break
            temperature = float(temp_input)
            if 0.0 <= temperature <= 2.0:
                break
            print("0.0 から 2.0 の間で入力してください。")
        except ValueError:
            print("数値を入力してください。")

    # 2. 仮想データの生成
    print_header("データの生成とFirestoreへの仮想保存")
    time.sleep(1)
    
    virtual_db = []
    
    if user_behavior == 1:
        print("👤 ユーザー: 「うまい！座布団一枚！」 (星5)")
        virtual_db.append({
            "odai": "AI",
            "text": "AIとかけて、ベテランの漫才師ととく。その心は、どちらも『間（ま）』が大事でしょう。",
            "ai_score": 4.5,
            "human_score": 5,
            "comment": "掛詞も綺麗で、現代的なお題に合っている。"
        })
    elif user_behavior == 2:
        print("👤 ユーザー: 「うーん、ベタすぎるかな」 (星1)")
        virtual_db.append({
            "odai": "警戒レベル",
            "text": "警戒レベルとかけて、SNSの炎上ととく。その心は、どちらもヒナン（避難/非難）が必要です。",
            "ai_score": 0.0,
            "human_score": 1,
            "comment": "ダブルミーニングは成立しているが、陳腐で面白みがない。"
        })
    elif user_behavior == 3:
        print("👤 ユーザー: 「あいうえおｗｗｗｗ」 (星1)")
        virtual_db.append({
            "odai": "宇宙",
            "text": "宇宙とかけて、校長先生の挨拶ととく。その心は、果てしなく長いです。",
            "ai_score": 4.8,
            "human_score": 1,
            "comment": "あいうえおｗｗｗｗつまんね"
        })

    print(f"💾 仮想Firestoreに {len(virtual_db)} 件のデータを保存しました (status: 2)")

    # 3. 治安維持パトロール（スパム判定）
    print_header("🚨 治安維持パトロールの実行")
    time.sleep(1)
    
    valid_data_for_ai = []
    for data in virtual_db:
        # スパムの簡易判定条件: 人間スコアが1 かつ AIスコアが極端に高い、またはコメントが不自然
        if data["human_score"] == 1 and data["ai_score"] > 4.0:
            print(f"❌ 警告: スパム認定しました。")
            print(f"   理由: AI高得点({data['ai_score']})に対して、不自然な低評価(星{data['human_score']})とコメント(「{data['comment']}」)が検出されました。")
            print("   → このデータはAIの学習(メタ分析)から除外されます。")
        else:
            print("✅ 正常な評価データとして承認されました。")
            valid_data_for_ai.append(data)

    # 4. AIメタ分析の実行
    if not valid_data_for_ai:
        print_header("🧠 AI自己反省会 (スキップ)")
        print("有効な学習データがありませんでした。シミュレーションを終了します。")
        return

    print_header("🧠 AI自己反省会 (メタ分析) の実行")
    print(f"Gemini API (gemini-3-flash-preview) を呼び出しています... (Temperature: {temperature})")
    
    feedback_text = ""
    for d in valid_data_for_ai:
        feedback_text += f"\n・お題: {d['odai']}\n・なぞかけ本文: {d['text']}\n・AIの予測スコア: {d['ai_score']} / 5.0相当\n・人間がつけた実際の星評価: {d['human_score']} / 5\n• 人間のコメント(理由): {d['comment']}\n"

    analysis_prompt = f"""
    あなたは天才的なプロンプトエンジニアであり、認知科学者です。
    以下のデータは、AIが生成・評価した「なぞかけ」に対する、実際の人間からのフィードバックです。

    【分析対象の評価データ】{feedback_text}

    【最重要・絶対遵守ルール】
    出力するレポートの【一番最初（冒頭）】に、今回分析対象となった「お題」と「なぞかけ本文」の組み合わせをすべて箇条書きで明記してください。
    
    【レポートの構成案】
    ■ 📋 今回の分析対象なぞかけ一覧
    ■ 1. 人間とAIの評価の差異についての認知科学的分析
    ■ 2. 今後のシステムプロンプトの具体的な改善案（ルール追加の提案）を2つ
    
    簡潔かつ専門的なトーンでレポートしてください。
    """

    try:
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=analysis_prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
            )
        )
        print("\n" + "="*20 + " 💡 改善レポート " + "="*20)
        print(response.text)
        print("="*55)
    except Exception as e:
        print(f"\n❌ APIの呼び出し中にエラーが発生しました:\n{e}")

if __name__ == "__main__":
    main()
