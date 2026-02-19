"""
파일 업로드 관련 API 엔드포인트
"""
import os
import io
import re
import shutil
import uuid
import zipfile
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


def _validate_and_extract_zip(zip_bytes: bytes, zip_filename: str):
    """
    ZIP 파일 검증 및 내용 추출

    규칙:
      - .md 파일이 정확히 1개
      - .jpeg/.jpg 파일이 0개 이상, 모두 _page_n_... 명명 규칙 준수
      - 그 외 파일은 허용하지 않음

    Returns:
        (doc_name: str, md_name: str, md_bytes: bytes, jpeg_data: dict[str, bytes])
    Raises:
        HTTPException: 규칙 위반 시
    """
    from fastapi import HTTPException
    PAGE_PATTERN = re.compile(r"^_page_\d+_.+\.jpe?g$", re.IGNORECASE)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # 디렉토리 엔트리 제외
            names = [n for n in zf.namelist() if not n.endswith("/")]

            md_files    = [n for n in names if n.lower().endswith(".md")]
            jpeg_files  = [n for n in names if re.search(r"\.jpe?g$", n, re.IGNORECASE)]
            other_files = [n for n in names if n not in md_files and n not in jpeg_files]

            if len(md_files) != 1:
                raise HTTPException(
                    status_code=400,
                    detail=f"ZIP 내에 .md 파일이 정확히 1개여야 합니다. (현재 {len(md_files)}개)"
                )

            if other_files:
                raise HTTPException(
                    status_code=400,
                    detail=f"ZIP 내에 .md / .jpeg 이외의 파일이 포함되어 있습니다: {other_files}"
                )

            invalid_jpegs = [
                os.path.basename(n) for n in jpeg_files
                if not PAGE_PATTERN.match(os.path.basename(n))
            ]
            if invalid_jpegs:
                raise HTTPException(
                    status_code=400,
                    detail=f"JPEG 파일명이 _page_n_... 규칙을 위반합니다: {invalid_jpegs}"
                )

            md_name  = os.path.basename(md_files[0])
            md_bytes = zf.read(md_files[0])
            doc_name = os.path.splitext(md_name)[0]

            jpeg_data: dict = {}
            for jpath in jpeg_files:
                jname = os.path.basename(jpath)
                jpeg_data[jname] = zf.read(jpath)

            return doc_name, md_name, md_bytes, jpeg_data

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="올바른 ZIP 파일이 아닙니다.")


@router.post("/", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    upload_svc = Depends(get_upload_service),
    rag_svc: RAGService = Depends(get_rag_service)
):
    """파일 업로드 (PDF, Markdown, ZIP 지원): 파일 저장 후 바로 응답하고 백그라운드에서 처리 시작"""
    fname_lower = file.filename.lower()

    if not fname_lower.endswith((".pdf", ".md", ".zip")):
        raise HTTPException(
            status_code=400,
            detail="PDF(.pdf), 마크다운(.md), 또는 ZIP(.zip) 파일만 업로드 가능합니다."
        )

    # ── ZIP 처리 분기 ─────────────────────────────────────────────
    if fname_lower.endswith(".zip"):
        raw = await file.read()

        doc_name, md_name, md_bytes, jpeg_data = _validate_and_extract_zip(raw, file.filename)

        md_path = os.path.join(settings.DATA_PATH, md_name)
        try:
            with open(md_path, "wb") as f:
                f.write(md_bytes)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"MD 파일 저장 실패: {e}")

        if jpeg_data:
            img_dir = os.path.join(settings.IMGS_PATH, doc_name)
            os.makedirs(img_dir, exist_ok=True)
            for jname, jbytes in jpeg_data.items():
                try:
                    with open(os.path.join(img_dir, jname), "wb") as f:
                        f.write(jbytes)
                except Exception as e:
                    print(f"[경고] 이미지 저장 실패 ({jname}): {e}")

        print(f"[ZIP] '{file.filename}' 추출 완료 -> MD: {md_name}, 이미지: {len(jpeg_data)}개")
        ingest_filename = md_name

    # ── PDF / MD 처리 (기존 로직) ─────────────────────────────────
    else:
        file_location = os.path.join(settings.DATA_PATH, file.filename)
        try:
            with open(file_location, "wb+") as file_object:
                shutil.copyfileobj(file.file, file_object)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"파일 저장 실패: {str(e)}")
        ingest_filename = file.filename

    task_id = str(uuid.uuid4())
    await upload_svc.create_upload_task(task_id, ingest_filename)

    asyncio.create_task(
        upload_svc.process_uploaded_file(task_id, ingest_filename, rag_svc)
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
