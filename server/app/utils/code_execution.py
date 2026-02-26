"""
코드 실행 관련 유틸리티
"""
import os
import sys
import subprocess
import tempfile

# TODO: 보안 강화 필요 - 현재는 단순 실행, 실제 환경에서는 샌드박스 필요

# matplotlib이 GUI 없이 백엔드를 Agg로 사용하도록 강제하는 프리앰블
_PREAMBLE = """\
import matplotlib
matplotlib.use('Agg')
"""


def execute_python_code(code: str, timeout: int = 60) -> str:
    """
    Python 코드를 로컬에서 실행하고 결과를 반환합니다.
    임시 파일 방식을 사용해 CLI 인자 길이 제한을 우회합니다.
    matplotlib은 자동으로 Agg 백엔드(비-GUI)로 설정됩니다.

    Args:
        code: 실행할 Python 코드
        timeout: 실행 시간 제한 (초, 기본 60)

    Returns:
        실행 결과 문자열 (stdout + stderr)
    """
    full_code = _PREAMBLE + code

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(full_code)
            tmp_path = tmp.name

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),  # 환경 변수 상속 -- 보안상 유의
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]: {result.stderr}"
        return output if output else "(출력 없음)"
    except subprocess.TimeoutExpired:
        return f"[Error: 코드 실행 타임아웃 ({timeout}초 초과)]"
    except Exception as e:
        return f"[Error executing code: {str(e)}]"
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass