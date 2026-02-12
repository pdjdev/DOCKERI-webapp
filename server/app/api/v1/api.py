"""
API v1 라우터
"""
from fastapi import APIRouter

from app.api.v1.endpoints import chat, upload, documents
from app.services import RAGService


# 전역 RAG 서비스 인스턴스
rag_service = RAGService()

# API v1 라우터
api_router = APIRouter()

# 각 엔드포인트 라우터들을 포함
api_router.include_router(chat.router)
api_router.include_router(upload.router)
api_router.include_router(documents.router)