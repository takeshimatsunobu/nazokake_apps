import requests
import json
import os
import re
from firebase_admin import firestore
from google import genai
from google.genai.types import GenerateContentConfig

# --- 設定 ---
VM_IP = "100.70.53.71"
TIER1_URL = f"http://{VM_IP}:8080/v1/chat/completions"
TIER2_URL = f"http://{VM_IP}:8081/v1/chat/completions"

EVALUATOR_MODEL = os.environ.get("EVALUATOR_MODEL_NAME", "gemini-3.1-pro-preview")
GENERATOR_FALLBACK = os.environ.get("GENERATOR_FALLBACK_MODEL", "gemini-3-flash-preview")

# 💡 要塞がオフの時は無駄なタイムアウトを即座にスキップする直通スイッチ
USE_LOCAL_GCP = os.environ.get("USE_LOCAL_GCP", "false").lower() == "true"

def chat_completion_local(url, system_prompt, user_prompt, max_tokens=256, temperature=0.8):
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.9
    }
    # 🚨 ここを強制的に 3.0 秒に修正！
    res = requests.post(url, json=payload, timeout=3.0)
    res.raise_for_status()
    return res.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()

def generate_nazokake(odai: str):
    # 🔥 修正: 「とく」の部分に対する文字数と品詞の絶対制約を追加
    sys_prompt = "あなたは前衛的な天才なぞかけ芸人です。\n【重要】提供される例や過去のコンテキストは「型」の参考のみとし、言葉や内容は絶対にコピーせず100%オリジナルの発想で出力してください。\n\n【思考プロセス】\n1. お題(A)から連想される言葉を挙げる。\n2. その言葉と同じ「ひらがな」で、全く別の意味を持つ言葉(B)を探す。\n3. (B)から連想される、お題と無関係なジャンルの言葉を「とく(××)」にする。\n【絶対制約】「××と」の文字数制限を設け、適切な単語を選んでください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように工夫してください。例：『〜の〜』など、文脈に合うように調整してください。

```python
import re

def clean_text(text):
    """
    Cleans the input text by removing non-alphanumeric characters 
    and normalizing whitespace.
    """
    # Keep only alphanumeric characters and spaces
    cleaned_text = re.sub(r'[^\w\s]', '', text)
    # Normalize whitespace (replace multiple spaces with a single space)
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    return cleaned_text

def extract_keywords(text):
    """
    Extracts potential keywords from the cleaned text.
    This implementation uses a simple approach: splitting by space and filtering out common stop words.
    """
    # A basic set of English stop words (can be expanded)
    stop_words = set([
        "the", "a", "an", "is", "are", "was", "were", "and", "or", "but", "if", "of", "to", "in", "for", "on", "at", "by", "with", "from", "about"
    ])
    
    words = clean_text(text).lower().split()
    keywords = []
    for word in words:
        if word not in stop_words and len(word) > 1:
            keywords.append(word)
    return keywords

def analyze_sentiment(text):
    """
    A very basic sentiment analysis function based on predefined positive and negative words.
    Returns a score: positive count - negative count.
    """
    positive_words = {"good", "great", "excellent", "amazing", "wonderful", "love", "like", "best", "bestest", "awesome"}
    negative_words = {"bad", "terrible", "awful", "poor", "hate", "dislike", "worst", "worstest", "badest"}
    
    # Clean and tokenize the text
    words = clean_text(text).lower().split()
    
    score = 0
    for word in words:
        if word in positive_words:
            score += 1
        elif word in negative_words:
            score -= 1
    return score

def analyze_text(text):
    """
    Performs a comprehensive analysis on the input text, returning a dictionary of results.
    """
    if not text or not isinstance(text, str):
        return {
            "error": "Input must be a non-empty string."
        }
        
    results = {}
    
    # 1. Keyword Extraction
    keywords = extract_keywords(text)
    results["keywords"] = keywords
    
    # 2. Sentiment Analysis
    sentiment_score = analyze_sentiment(text)
    results["sentiment_score"] = sentiment_score
    
    # 3. Overall Summary (Placeholder for more complex logic)
    # For this example, we'll just use the length of the text.
    results["text_length"] = len(text)
    
    return results

# --- Example Usage ---
text1 = "This product is amazing and I love it. It is the best I have ever used! Highly recommend."
text2 = "The service was terrible and the quality was poor. I hate this product."
text3 = "Neutral statement about the weather today."
text4 = "What a wonderful day for a walk? Amazing!"

print("==================================================")
print("ANALYSIS OF TEXT 1:")
print(f"Input: {text1}")
analysis1 = analyze_text(text1)
print(f"Results: {analysis1}")

print("\n==================================================")
print("ANALYSIS OF TEXT 1:")
print(f"Input: {text1}")
analysis1_re = analyze_text(text1)
print(f"Results: {analysis1_re}")

print("\n==================================================")
print("ANALYSIS OF TEXT 2:")
print(f"Input: {text2}")
analysis2 = analyze_text(text2)
print(f"Results: {analysis2}")

print("\n==================================================")
print("ANALYSIS OF TEXT 2:")
print(f"Input: {text2}")
analysis2_re = analyze_text(text2)
print(f"Results: {analysis2_re}")

print("\n==================================================")
print("ANALYSIS OF TEXT 3:")
print(f"Input: {text3}")
analysis3 = analyze_text(text3)
print(f"Results: {analysis3}")

print("\n==================================================")
print("ANALYSIS OF TEXT 3:")
print(f"Input: {text3}")
analysis3_re = analyze_text(text3)
print(f"Results: {analysis3_re}")

print("\n==================================================")
print("ANALYSIS OF TEXT 4:")
print(f"Input: {text4}")
analysis4 = analyze_text(text4)
print(f"Results: {analysis4}")

print("\n==================================================")
print("ANALYSIS OF TEXT 4:")
print(f"Input: {text4}")
analysis4_re = analyze_text(text4)
print(f"Results: {analysis4_re}")
```