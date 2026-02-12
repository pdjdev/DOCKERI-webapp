"""
모델 스키마 정의 (Pydantic 사용)
"""
from typing import List
from pydantic import BaseModel, Field


class Part(BaseModel):
    """Gemini API 스타일의 메시지 파트"""
    text: str


class Content(BaseModel):
    """Gemini API 스타일의 메시지 컨텐트"""
    role: str
    parts: List[Part]


class ChatRequest(BaseModel):
    """채팅 요청 스키마"""
    # Gemini API 스타일의 구조화된 입력 (대화 히스토리 포함)
    contents: List[Content]
    
    # 선택적 설정
    temperature: float = Field(default=0.1, ge=0.0, le=2.0, description="응답의 창의성 조절 (0.0-2.0)")


class DocumentListResponse(BaseModel):
    """문서 목록 응답 스키마"""
    count: int
    documents: List[str]


class UploadResponse(BaseModel):
    """파일 업로드 응답 스키마"""
    task_id: str
    message: str


class UploadStatusResponse(BaseModel):
    """업로드 상태 응답 스키마"""
    task_id: str
    status: str
    message: str
    filename: str
    created_at: str
    updated_at: str
    progress: int


class IngestResponse(BaseModel):
    """문서 처리 응답 스키마"""
    message: str


class DeleteDocumentResponse(BaseModel):
    """문서 삭제 응답 스키마"""
    message: str
    db_deleted: bool
    file_deleted: bool