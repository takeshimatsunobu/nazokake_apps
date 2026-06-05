import os
from dotenv import load_dotenv
load_dotenv()  # .envファイルからAPIキーを読み込む

import firebase_admin

if not firebase_admin._apps:
    firebase_admin.initialize_app()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import endpoints

app = FastAPI(title="なぞかけディスカバリー API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001", "https://nazokakeapp-137e5.web.app", "https://nazokakeapp-137e5.firebaseapp.com"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(endpoints.router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "Nazokake Backend is running on Cloud Run!"}

