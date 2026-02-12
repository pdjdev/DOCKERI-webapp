"""
문서 관리 관련 API 엔드포인트
"""
import os
import asyncio
from fastapi import APIRouter, HTTPException, Depends

from app.models import DocumentListResponse, IngestResponse, DeleteDocumentResponse
from app.config import settings
from app.services import RAGService


router = APIRouter(prefix="/documents", tags=["documents"])


def get_rag_service() -> RAGService:
    """RAG 서비스 의존성 주입"""
    from app.api.v1.api import rag_service
    return rag_service


@router.post("/ingest", response_model=IngestResponse)
async def trigger_ingest(rag_svc: RAGService = Depends(get_rag_service)):
    """
    수동으로 전체 문서 재처리를 요청할 때 사용
    (파일 업로드 흐름이 아니라 전체 docs 폴더를 다시 스캔하고 싶을 때)
    """
    try:
        # 이 엔드포인트는 동기로 기다림 (오래 걸릴 수 있음 주의)
        # 필요하다면 백그라운드 태스크로 전환 가능
        result = await asyncio.to_thread(rag_svc.ingest_documents)
        return IngestResponse(message=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=DocumentListResponse)
async def list_documents(rag_svc: RAGService = Depends(get_rag_service)):
    """저장된 문서 목록 조회"""
    docs = rag_svc.get_document_list()
    return DocumentListResponse(count=len(docs), documents=docs)


@router.delete("/", response_model=DeleteDocumentResponse) 
async def delete_document_endpoint(
    filename: str, 
    rag_svc: RAGService = Depends(get_rag_service)
):
    """문서 삭제 (벡터 DB와 파일 시스템에서 모두 삭제)"""
    db_deleted = rag_svc.delete_document(filename)
    file_path = os.path.join(settings.DATA_PATH, filename)
    file_deleted = False
    if os.path.exists(file_path):
        os.remove(file_path)
        file_deleted = True
    
    if not db_deleted and not file_deleted:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
        
    return DeleteDocumentResponse(
        message="삭제 완료", 
        db_deleted=db_deleted, 
        file_deleted=file_deleted
    )