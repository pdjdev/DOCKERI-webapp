"""
파일 업로드 관련 API 엔드포인트
"""
import os
import shutil
import uuid
import asyncio
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends

from app.models import UploadResponse, UploadStatusResponse
from app.config import settings
from app.services import RAGService, upload_service


router = APIRouter(prefix="/upload", tags=["upload"])


def get_rag_service() -> RAGService:
    """RAG 서비스 의존성 주입"""
    from app.api.v1.api import rag_service
    return rag_service


def get_upload_service():
    """업로드 서비스 의존성 주입"""
    return upload_service


@router.post("/", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    upload_svc = Depends(get_upload_service),
    rag_svc: RAGService = Depends(get_rag_service)
):
    """파일 업로드 (PDF 및 Markdown 지원): 파일 저장 후 바로 응답하고 백그라운드에서 처리 시작"""
    # PDF와 Markdown 확장자 허용
    if not file.filename.lower().endswith(('.pdf', '.md')):
        raise HTTPException(status_code=400, detail="PDF(.pdf) 또는 마크다운(.md) 파일만 업로드 가능합니다.")

    file_location = os.path.join(settings.DATA_PATH, file.filename)
    try:
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파일 저장 실패: {str(e)}")

    task_id = str(uuid.uuid4())
    await upload_svc.create_upload_task(task_id, file.filename)

    # 백그라운드로 처리 시작 (이 함수는 논블로킹)
    asyncio.create_task(
        upload_svc.process_uploaded_file(task_id, file.filename, rag_svc)
    )

    return UploadResponse(
        task_id=task_id, 
        message=f"파일 '{file.filename}' 업로드 완료. 처리 시작됨"
    )


@router.get("/status/{task_id}", response_model=UploadStatusResponse)
async def upload_status(task_id: str, upload_svc = Depends(get_upload_service)):
    """업로드 및 처리 상태를 폴링하기 위한 엔드포인트"""
    info = await upload_svc.get_task_status(task_id)
    if not info:
        raise HTTPException(status_code=404, detail="해당 task_id를 찾을 수 없습니다.")
    
    return UploadStatusResponse(task_id=task_id, **info)


@router.get("/tasks")
async def list_upload_tasks(upload_svc = Depends(get_upload_service)):
    """모든 업로드 태스크 목록 반환"""
    return await upload_svc.list_all_tasks()