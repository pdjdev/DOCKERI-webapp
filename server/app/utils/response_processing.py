"""
모델 응답 처리 및 히스토리 파싱 유틸리티
"""
from typing import List, Tuple
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from app.models.schemas import Content
from app.utils.code_execution import execute_python_code


def process_model_response(response) -> str:
    """
    모델 응답에서 code_execution_result를 처리하고 최종 텍스트를 생성합니다.
    response.content_blocks 형태의 응답을 파싱합니다.
    
    Args:
        response: 모델 응답 객체
        
    Returns:
        처리된 최종 텍스트
    """
    if not hasattr(response, 'content_blocks') or not response.content_blocks:
        # 일반 텍스트 응답
        return str(response) if hasattr(response, '__str__') else ""
    
    final_text = ""
    
    for block in response.content_blocks:
        block_type = block.get('type') if isinstance(block, dict) else getattr(block, 'type', None)
        
        # 텍스트 블록 처리
        if block_type == 'text':
            text = block.get('text') if isinstance(block, dict) else getattr(block, 'text', '')
            final_text += text
        
        # 코드 실행 호출 블록 처리
        elif block_type == 'server_tool_call':
            if isinstance(block, dict):
                name = block.get('name')
                args = block.get('args', {})
            else:
                name = getattr(block, 'name', '')
                args = getattr(block, 'args', {})
            
            if name == 'code_interpreter':
                code = args.get('code') if isinstance(args, dict) else getattr(args, 'code', '')
                if code:
                    execution_result = execute_python_code(code)
                    final_text += f"\n\n[Code executed]:\n{code}\n\n[Output]:\n{execution_result}"
        
        # 코드 실행 결과 블록 처리 (이미 실행된 결과 표시)
        elif block_type == 'server_tool_result':
            if isinstance(block, dict):
                output = block.get('output', '')
                status = block.get('status', '')
            else:
                output = getattr(block, 'output', '')
                status = getattr(block, 'status', '')
            
            if output:
                final_text += f"\n[Result]:\n{output}"
    
    return final_text


def parse_history(contents: List[Content]) -> Tuple[str, List[BaseMessage]]:
    """
    JSON 입력(contents)을 파싱하여:
    1. 최신 질문 (last_query)
    2. LangChain 형식의 대화 히스토리 (history_messages)
    로 분리합니다.
    
    Args:
        contents: 대화 내용 리스트
        
    Returns:
        (현재 질문, 히스토리 메시지 리스트) 튜플
    """
    history_messages = []
    
    # 마지막 메시지는 '현재 질문'으로 간주
    if not contents:
        return "", []
        
    last_content = contents[-1]
    last_query = " ".join([p.text for p in last_content.parts])
    
    # 마지막 메시지를 제외한 나머지를 히스토리로 변환
    for content in contents[:-1]:
        text = " ".join([p.text for p in content.parts])
        if content.role == "user":
            history_messages.append(HumanMessage(content=text))
        elif content.role == "model":
            history_messages.append(AIMessage(content=text))
            
    return last_query, history_messages