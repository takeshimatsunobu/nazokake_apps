# 1. Python公式スリムイメージ（軽量・セキュア）を使用
FROM python:3.11-slim

# 2. 作業ディレクトリの設定
WORKDIR /app

# 3. 依存ライブラリのインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. ソースコードのコピー
COPY . .

# 5. Cloud Run環境変数の設定
ENV STREAMLIT_SERVER_PORT=8080
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0

# 6. アプリケーションの起動
EXPOSE 8080
CMD ["streamlit", "run", "app.py"]