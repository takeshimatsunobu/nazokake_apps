# 1. 軽量でセキュアなPython公式スリムイメージを使用
FROM python:3.11-slim

# 2. コンテナ内の作業ディレクトリを設定
WORKDIR /app

# 3. 依存関係のコピーとインストール
# --no-cache-dir を指定して不要なキャッシュを残さず、イメージサイズを削減する
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. アプリケーションコード（main.py, firestore_db.py, gemini_api.pyなど）をコピー
COPY . .

# 5. Cloud Runの要件に従い、0.0.0.0のポート8080でリッスンする
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]