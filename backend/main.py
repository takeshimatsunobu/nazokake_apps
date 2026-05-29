import firebase_admin

# 🔥 超重要：APIを読み込む「前」にFirebaseを初期化する
if not firebase_admin._apps:
    firebase_admin.initialize_app()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import endpoints

app = FastAPI(title="なぞかけディスカバリー API")

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔥 修正：フロントエンドの呼び出し先と合わせるため、prefix="/api" を追加！
app.include_router(endpoints.router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "Nazokake Backend is running on Cloud Run!"}
