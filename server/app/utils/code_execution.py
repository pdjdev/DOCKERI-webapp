"""
코드 실행 관련 유틸리티
"""
import os
import sys
import subprocess
import tempfile

# TODO: 보안 강화 필요 - 현재는 단순 실행, 실제 환경에서는 샌드박스 필요

# matplotlib 백엔드 + 한글 폰트 자동 설정 프리앰블
_PREAMBLE = """\
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as _plt_setup
import matplotlib.font_manager as _fm

def _setup_korean_font():
    # 우선순위 순으로 한글 지원 폰트 후보 목록
    _candidates = [
        'Malgun Gothic',      # Windows 기본 한글 폰트
        'NanumGothic',        # 나눔고딕
        'NanumBarunGothic',   # 나눔바른고딕
        'AppleGothic',        # macOS
        'UnDotum',            # Linux
        'Noto Sans KR',
        'Noto Sans CJK KR',
        'Noto Sans CJK JP',   # CJK fallback
    ]
    _available = {f.name for f in _fm.fontManager.ttflist}
    for _font in _candidates:
        if _font in _available:
            _plt_setup.rcParams['font.family'] = _font
            break
    _plt_setup.rcParams['axes.unicode_minus'] = False  # 마이너스 기호 깨짐 방지

_setup_korean_font()
del _setup_korean_font, _plt_setup, _fm
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