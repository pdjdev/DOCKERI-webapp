"""
DOCKERI 웹앱 FastAPI 서버 진입점
"""
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.config import settings
from app.services import upload_service


# FastAPI 앱 생성
app = FastAPI(
    title="DOCKERI API (Streaming)", 
    description="전기 기술 문서 RAG 시스템",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 구체적 도메인 설정 권장
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 포함
app.include_router(api_router)


@app.on_event("startup")
async def startup_tasks():
    """앱 시작시 실행할 태스크들"""
    # 업로드 태스크 상태 복원
    await upload_service.load_tasks_from_file()
    
    # 백그라운드 정리 데몬 시작
    asyncio.create_task(upload_service.cleanup_old_tasks())


@app.get("/")
async def root():
    """루트 엔드포인트 - 헬스체크"""
    return {
        "message": "DOCKERI API Server",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """헬스체크 엔드포인트"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True
    )