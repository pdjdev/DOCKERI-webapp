"""
채팅 관련 API 엔드포인트
"""
import os
import re
import html
import base64
import traceback
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.models import ChatRequest
from app.config import settings
from app.utils import parse_history
from app.services import RAGService


router = APIRouter(prefix="/chat", tags=["chat"])

# 마크다운 이미지 참조 패턴: ![](_page_n_xxx.jpeg)
_IMG_REF_PATTERN = re.compile(r"!\[.*?\]\((_page_\d+_[^\)]+\.jpe?g)\)", re.IGNORECASE)


def get_rag_service() -> RAGService:
    """RAG 서비스 의존성 주입"""
    from app.api.v1.api import rag_service
    return rag_service


def _extract_image_paths(retrieved_docs) -> list[str]:
    """
    검색된 문서 청크에서 이미지 참조를 추출하고,
    docs/imgs/{문서명}/{파일명} 경로에 파일이 실제로 존재하는 경우만 반환합니다.
    """
    image_paths = []
    seen = set()

    for doc in retrieved_docs:
        source = os.path.basename(doc.metadata.get("source", ""))
        doc_name = os.path.splitext(source)[0]
        content  = doc.page_content

        for match in _IMG_REF_PATTERN.finditer(content):
            img_filename = match.group(1)
            img_path = os.path.join(settings.IMGS_PATH, doc_name, img_filename)

            if img_path not in seen:
                seen.add(img_path)
                if os.path.isfile(img_path):
                    image_paths.append(img_path)
                    print(f"이미지 참조: docs/imgs/{doc_name}/{img_filename}")

    return image_paths


def _build_image_parts(image_paths: list[str]) -> list[dict]:
    """이미지 파일을 base64로 인코딩하여 LangChain 멀티모달 파트 목록 반환"""
    parts = []
    for img_path in image_paths:
        try:
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            # JPEG 인지 JPG 인지 확인
            mime = "image/jpeg"
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
        except Exception as e:
            print(f"[경고] 이미지 로드 실패 ({img_path}): {e}")
    return parts


@router.post("/")
async def chat_stream_endpoint(
    request: ChatRequest,
    rag_svc: RAGService = Depends(get_rag_service)
):
    """
    구조화된 대화 이력을 받아 스트리밍 응답을 제공합니다.
    code_interpreter 기능 및 ZIP 문서 이미지 멀티모달 참조를 지원합니다.
    """
    # 1. 시스템 준비 확인
    if not rag_svc.retriever:
        raise HTTPException(status_code=503, detail="시스템 초기화 전이거나 문서가 없습니다.")

    # 2. 입력 파싱 (질문과 히스토리 분리)
    current_query, history = parse_history(request.contents)

    if not current_query:
        raise HTTPException(status_code=400, detail="질문 내용이 없습니다.")

    # 3. 문서 검색
    retrieved_docs = await rag_svc.retriever.ainvoke(current_query)

    # 4. 참조 이미지 추출 (ZIP 문서에서 온 청크에만 해당)
    image_paths = _extract_image_paths(retrieved_docs)
    image_parts = _build_image_parts(image_paths)

    # 5. LLM 준비 (code_interpreter 바인딩)
    llm = ChatGoogleGenerativeAI(
        model=settings.LLM_MODEL,
        temperature=request.temperature,
        streaming=True,
    )
    llm = llm.bind_tools([{"code_execution": {}}])

    context_text = "\n\n".join(doc.page_content for doc in retrieved_docs)

    system_content = (
        "당신은 KERI 기술 지원 전문가입니다. 아래 제공된 [참고 문서] 내용을 바탕으로 질문에 답변하세요. "
        "필요한 경우 Python 코드를 실행하여 계산이나 분석을 수행할 수 있습니다. "
        "문서에 내용이 없다면 '해당 내용은 문서에서 찾을 수 없습니다'라고 답변하세요.\n\n"
        f"[참고 문서]\n{context_text}"
    )

    # 6. 메시지 목록 구성 (멀티모달 HumanMessage 포함)
    system_msg = SystemMessage(content=system_content)

    # 이미지가 있으면 멀티모달 파트로 HumanMessage 구성
    if image_parts:
        human_content = [{"type": "text", "text": current_query}] + image_parts
        human_msg = HumanMessage(content=human_content)
    else:
        human_msg = HumanMessage(content=current_query)

    messages = [system_msg] + history + [human_msg]

    # 7. 비동기 제너레이터 함수 정의
    async def response_generator():
        try:
            async for chunk in llm.astream(messages):
                # content_blocks가 있으면 우선 처리 (code execution 포함)
                if hasattr(chunk, "content_blocks") and chunk.content_blocks:
                    for block in chunk.content_blocks:
                        block_type = (
                            getattr(block, "type", None)
                            if hasattr(block, "type")
                            else block.get("type")
                            if isinstance(block, dict)
                            else None
                        )

                        # 텍스트 블록
                        if block_type == "text":
                            text = (
                                getattr(block, "text", "")
                                if hasattr(block, "text")
                                else block.get("text", "")
                            )
                            if text:
                                yield text

                        # 코드 실행 호출 감지
                        elif block_type == "server_tool_call":
                            name = (
                                getattr(block, "name", "")
                                if hasattr(block, "name")
                                else block.get("name", "")
                            )
                            if name == "code_interpreter":
                                args = (
                                    getattr(block, "args", {})
                                    if hasattr(block, "args")
                                    else block.get("args", {})
                                )
                                code = (
                                    getattr(args, "code", "")
                                    if hasattr(args, "code")
                                    else args.get("code", "")
                                )
                                if code:
                                    yield f"\n\n<code-execute>{code}</code-execute>\n\n"

                        # 코드 실행 결과
                        elif block_type == "server_tool_result":
                            output = (
                                getattr(block, "output", "")
                                if hasattr(block, "output")
                                else block.get("output", "")
                            )
                            if output:
                                yield f"<code-print>{output}</code-print>\n\n"

                # content_blocks가 없을 때만 일반 content 처리 (중복 방지)
                elif (
                    hasattr(chunk, "content")
                    and isinstance(chunk.content, str)
                    and chunk.content
                ):
                    yield chunk.content

            # 답변 완료 후 출처 정보 전송
            if retrieved_docs:
                sources_text = "\n\n<div class='sources'><p class='sources-title'>참고 자료</p><ul>"
                for doc in retrieved_docs:
                    source = os.path.basename(doc.metadata.get("source", "Unknown"))
                    snippet = doc.page_content[:100].replace("\n", " ") + (
                        "..." if len(doc.page_content) > 100 else ""
                    )
                    escaped_snippet = html.escape(snippet, quote=True)
                    sources_text += (
                        f"<li><span class='source-name'>{source}:</span> "
                        f"<span class='source-snippet'>{escaped_snippet}</span></li>"
                    )
                sources_text += "</ul></div>"
                yield sources_text

        except Exception as e:
            yield f"\n\n[Error occurred: {str(e)}]"
            traceback.print_exc()

    # 8. StreamingResponse 반환 (버퍼링 방지 헤더 추가)
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Content-Type": "text/plain; charset=utf-8",
    }

    return StreamingResponse(
        response_generator(),
        media_type="text/plain",
        headers=headers,
    )
