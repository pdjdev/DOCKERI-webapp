"""
채팅 관련 API 엔드포인트
"""
import os
import html
import traceback
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.models import ChatRequest
from app.config import settings
from app.utils import parse_history
from app.services import RAGService


router = APIRouter(prefix="/chat", tags=["chat"])


def get_rag_service() -> RAGService:
    """RAG 서비스 의존성 주입"""
    from app.api.v1.api import rag_service
    return rag_service


@router.post("/")
async def chat_stream_endpoint(
    request: ChatRequest, 
    rag_svc: RAGService = Depends(get_rag_service)
):
    """
    구조화된 대화 이력을 받아 스트리밍 응답을 제공합니다.
    code_interpreter 기능을 지원하여 Python 코드를 실행할 수 있습니다.
    """
    # 1. 시스템 준비 확인
    if not rag_svc.retriever:
        raise HTTPException(status_code=503, detail="시스템 초기화 전이거나 문서가 없습니다.")

    # 2. 입력 파싱 (질문과 히스토리 분리)
    current_query, history = parse_history(request.contents)
    
    if not current_query:
        raise HTTPException(status_code=400, detail="질문 내용이 없습니다.")

    # 3. 문서 검색 (Sources 확보를 위해 미리 수행)
    retrieved_docs = await rag_svc.retriever.ainvoke(current_query)
    
    # 4. 체인 준비 (code_interpreter 활성화)
    llm = ChatGoogleGenerativeAI(
        model=settings.LLM_MODEL, 
        temperature=request.temperature, 
        streaming=True
    )
    
    # Code Interpreter 바인딩
    llm = llm.bind_tools([{"code_execution": {}}])
    
    context_text = "\n\n".join(doc.page_content for doc in retrieved_docs)
    
    system_prompt = (
        "당신은 KERI 기술 지원 전문가입니다. 아래 제공된 [참고 문서] 내용을 바탕으로 질문에 답변하세요. "
        "필요한 경우 Python 코드를 실행하여 계산이나 분석을 수행할 수 있습니다. "
        "문서에 내용이 없다면 '해당 내용은 문서에서 찾을 수 없습니다'라고 답변하세요.\n\n"
        "[참고 문서]\n{context}"
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{question}"),
    ])
    
    # Context를 미리 주입한 체인 생성 (StrOutputParser 제거, 직접 처리)
    chain = prompt | llm

    # 5. 비동기 제너레이터 함수 정의
    async def response_generator():
        try:
            # (1) 답변 스트리밍 - content_blocks 처리
            async for chunk in chain.astream({
                "context": context_text,
                "history": history,
                "question": current_query
            }):
                # content_blocks가 있으면 우선 처리 (code execution 포함)
                if hasattr(chunk, 'content_blocks') and chunk.content_blocks:
                    for block in chunk.content_blocks:
                        block_type = getattr(block, 'type', None) if hasattr(block, 'type') else block.get('type') if isinstance(block, dict) else None
                        
                        # 텍스트 블록
                        if block_type == 'text':
                            text = getattr(block, 'text', '') if hasattr(block, 'text') else block.get('text', '')
                            if text:
                                yield text
                        
                        # 코드 실행 호출 감지
                        elif block_type == 'server_tool_call':
                            name = getattr(block, 'name', '') if hasattr(block, 'name') else block.get('name', '')
                            if name == 'code_interpreter':
                                args = getattr(block, 'args', {}) if hasattr(block, 'args') else block.get('args', {})
                                code = getattr(args, 'code', '') if hasattr(args, 'code') else args.get('code', '')
                                if code:
                                    yield f"\n\n<code-execute>{code}</code-execute>\n\n"
                        
                        # 코드 실행 결과
                        elif block_type == 'server_tool_result':
                            output = getattr(block, 'output', '') if hasattr(block, 'output') else block.get('output', '')
                            if output:
                                yield f"<code-print>{output}</code-print>\n\n"
                
                # content_blocks가 없을 때만 일반 content 처리 (중복 방지)
                elif hasattr(chunk, 'content') and isinstance(chunk.content, str) and chunk.content:
                    yield chunk.content

            # (2) 답변 완료 후 출처 정보 전송
            if retrieved_docs:
                unique_sources = sorted(list(set(
                    os.path.basename(doc.metadata.get('source', 'Unknown')) 
                    for doc in retrieved_docs
                )))
                sources_text = "\n\n<div class='sources'><p class='sources-title'>참고 자료</p>"
                sources_text += "<ul>"

                # 참고한 파트도 일부 (최대 100자) 함께 제공
                for doc in retrieved_docs:
                    source = os.path.basename(doc.metadata.get('source', 'Unknown'))
                    snippet = doc.page_content[:100].replace("\n", " ") + ("..." if len(doc.page_content) > 100 else "")
                    # HTML 특수문자 이스케이프 처리 (마크다운, HTML 태그 등 방지)
                    escaped_snippet = html.escape(snippet, quote=True)
                    sources_text += f"<li><span class='source-name'>{source}:</span> <span class='source-snippet'>{escaped_snippet}</span></li>"

                sources_text += "</ul>"

                yield sources_text + "</div>"

        except Exception as e:
            # 스트리밍 도중 에러 발생 시
            yield f"\n\n[Error occurred: {str(e)}]"
            traceback.print_exc()

    # 6. StreamingResponse 반환 (버퍼링 방지 헤더 추가)
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no", # Nginx 버퍼링 방지 (핵심)
        "Content-Type": "text/plain; charset=utf-8"
    }

    return StreamingResponse(
        response_generator(), 
        media_type="text/plain",
        headers=headers
    )