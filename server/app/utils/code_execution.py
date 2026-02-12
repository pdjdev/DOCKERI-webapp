"""
코드 실행 관련 유틸리티
"""
import os
import sys
import subprocess


def execute_python_code(code: str, timeout: int = 10) -> str:
    """
    Python 코드를 실행하고 결과를 반환합니다.
    Code Interpreter용 헬퍼 함수
    
    Args:
        code: 실행할 Python 코드
        timeout: 실행 시간 제한 (초)
        
    Returns:
        실행 결과 문자열
    """
    try:
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy()  # 환경 변수 상속
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]: {result.stderr}"
        return output if output else "(출력 없음)"
    except subprocess.TimeoutExpired:
        return f"[Error: 코드 실행 타임아웃 ({timeout}초 초과)]"
    except Exception as e:
        return f"[Error executing code: {str(e)}]"