FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONPATH="/app:/app/backend"

# Cloud Runに「8080番を開けるぞ」と明示
EXPOSE 8080

# $PORT展開に頼らず8080を直書きし、CORSを無効化する最強の起動コマンド
CMD streamlit run service_frontend/admin_app.py --server.port 8080 --server.address 0.0.0.0 --server.enableCORS false --server.headless true
