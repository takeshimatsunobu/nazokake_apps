import os
from google import genai

def get_frontend_hint(a_title: str, b_title: str):
    """
    フロントエンド用: ユーザーへのヒントや下書きを高速生成
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    
    prompt = f"「{a_title}」と「{b_title}」を使ったなぞかけのヒントを1行で出してください。"
    
    # 💡 フロントエンド専用モデル（高速・軽量）
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite-preview",
        contents=prompt
    )
    return response.text

if __name__ == "__main__":
    # 動作テスト用
    print("🤖 Frontend AI (Lite) Response:")
    print(get_frontend_hint("人工知能", "優秀な秘書"))
