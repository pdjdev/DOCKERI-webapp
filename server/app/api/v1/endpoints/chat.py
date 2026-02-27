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
from app.utils.code_execution import execute_python_code
from app.services import RAGService


router = APIRouter(prefix="/chat", tags=["chat"])

# 마크다운 이미지 참조 패턴: ![](_page_n_xxx.jpeg/.jpg/.png)
_IMG_REF_PATTERN = re.compile(r"!\[.*?\]\((_page_\d+_[^\)]+\.(?:jpe?g|png))\)", re.IGNORECASE)


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
            mime = "image/png" if img_path.lower().endswith(".png") else "image/jpeg"
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

    context_text = "\n\n".join(doc.page_content for doc in retrieved_docs)

    system_content = (
        "당신은 KERI 기술 지원 전문가입니다. 아래 제공된 [참고 문서] 내용을 바탕으로 질문에 답변하세요. "
        "문서에 내용이 없다면 '해당 내용은 문서에서 찾을 수 없습니다'라고 답변하세요.\n\n"
        "━━━ 코드 실행 원칙 ━━━\n"
        "수치 계산, 데이터 분석, 그래프·차트·플롯·시각화 요청이 있으면 **반드시** "
        "Python 코드를 `<code-execute>` 태그로 감싸서 출력하세요. "
        "이 태그 안의 코드는 서버의 로컬 Python 인터프리터가 직접 실행합니다.\n"
        "코드 예시를 텍스트로만 제시하지 말고, 반드시 `<code-execute>` 태그를 사용하세요.\n\n"
        "━━━ 그래프·플롯 출력 규칙 ━━━\n"
        "그래프·차트·플롯 등 시각화 코드를 실행할 때는 아래 규칙을 **엄격히** 따르세요.\n\n"
        "1. `_save_plot_as_b64()` 함수는 실행 환경에 **미리 정의**되어 있습니다. "
        "별도로 정의할 필요 없이 바로 호출하면 됩니다.\n"
        "2. `plt.show()` 를 절대 호출하지 말고, 그래프 완성 후 반드시 `_save_plot_as_b64()` 를 호출하세요.\n"
        "3. `_save_plot_as_b64()` 가 출력하는 `<b64img>…</b64img>` 문자열을 텍스트 응답에 절대 인용·반복하지 마세요. "
        "그 문자열은 UI가 자동으로 이미지로 변환합니다.\n"
        "4. 그래프가 생성되었음을 응답에서 언급할 때는 '실행 결과에 그래프가 표시됩니다.'처럼 짧게만 작성하세요.\n\n"
        "올바른 사용 예시:\n"
        "<code-execute>\n"
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1,2,3], [4,5,6])\n"
        "_save_plot_as_b64()  # plt.show() 대신\n"
        "</code-execute>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
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
    # LLM이 <code-execute>...</code-execute> 태그로 코드를 출력하면
    # 로컬 Python 인터프리터가 직접 실행하고 결과를 <code-print> 태그로 반환합니다.
    _TAG_OPEN  = "<code-execute>"
    _TAG_CLOSE = "</code-execute>"

    async def response_generator():
        try:
            buf = ""  # 스트리밍 청크 버퍼

            async for chunk in llm.astream(messages):
                # 텍스트 내용 추출
                if hasattr(chunk, "content") and isinstance(chunk.content, str):
                    text = chunk.content
                elif hasattr(chunk, "content_blocks") and chunk.content_blocks:
                    text = ""
                    for block in chunk.content_blocks:
                        btype = (
                            block.get("type") if isinstance(block, dict)
                            else getattr(block, "type", None)
                        )
                        if btype == "text":
                            text += (
                                block.get("text", "") if isinstance(block, dict)
                                else getattr(block, "text", "")
                            )
                else:
                    continue

                if not text:
                    continue

                buf += text

                # 버퍼에서 완성된 <code-execute> 블록을 반복 처리
                while True:
                    open_pos = buf.find(_TAG_OPEN)
                    if open_pos == -1:
                        # 태그 없음 — 태그 시작이 잘릴 수 있으니 끝 일부는 보류
                        safe = len(buf) - len(_TAG_OPEN) + 1
                        if safe > 0:
                            yield buf[:safe]
                            buf = buf[safe:]
                        break

                    # 태그 앞 텍스트 즉시 전송
                    if open_pos > 0:
                        yield buf[:open_pos]
                        buf = buf[open_pos:]
                        open_pos = 0

                    close_pos = buf.find(_TAG_CLOSE, len(_TAG_OPEN))
                    if close_pos == -1:
                        # 닫힘 태그 아직 미도착 — 계속 버퍼링
                        break

                    # 완성된 코드 블록 추출 및 로컬 실행
                    code = buf[len(_TAG_OPEN):close_pos]
                    buf  = buf[close_pos + len(_TAG_CLOSE):]

                    yield f"\n\n{_TAG_OPEN}{code}{_TAG_CLOSE}\n\n"

                    import asyncio
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None, execute_python_code, code
                    )
                    yield f"<code-print>{result}</code-print>\n\n"

            # 스트림 종료 후 남은 버퍼 처리
            if buf:
                open_pos  = buf.find(_TAG_OPEN)
                close_pos = buf.find(_TAG_CLOSE)
                if open_pos != -1 and close_pos != -1 and close_pos > open_pos:
                    yield buf[:open_pos]
                    code = buf[open_pos + len(_TAG_OPEN):close_pos]
                    tail = buf[close_pos + len(_TAG_CLOSE):]
                    yield f"\n\n{_TAG_OPEN}{code}{_TAG_CLOSE}\n\n"
                    import asyncio
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None, execute_python_code, code
                    )
                    yield f"<code-print>{result}</code-print>\n\n"
                    if tail:
                        yield tail
                else:
                    yield buf

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
