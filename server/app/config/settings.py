"""
애플리케이션 설정 관리
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()


class Settings:
    """애플리케이션 설정"""
    
    # API 키
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
    
    # 패스 설정
    MODEL_PATH: str = './bge-m3'  # 로컬 모델 경로 또는 HuggingFace ID
    DB_PATH: str = 'vectorstore/db_faiss'
    DATA_PATH: str = './docs'
    
    # 태스크 관련 설정
    TASKS_FILE: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "upload_tasks.yaml")
    TASK_RETENTION_DAYS: int = int(os.getenv("TASK_RETENTION_DAYS", "7"))
    
    # 서버 설정
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # LLM 설정
    DEFAULT_TEMPERATURE: float = 0.1
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-2.5-flash")
    
    # 벡터 검색 설정
    RETRIEVAL_K: int = int(os.getenv("RETRIEVAL_K", "4"))
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "1000"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "100"))
    
    def __init__(self):
        """설정 초기화 및 검증"""
        self._validate_settings()
        self._create_directories()
    
    def _validate_settings(self):
        """필수 설정 검증"""
        if not self.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY가 .env 파일에 정의되어 있지 않습니다.")
    
    def _create_directories(self):
        """필요한 디렉토리 생성"""
        os.makedirs(self.DATA_PATH, exist_ok=True)
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)


# 전역 설정 인스턴스
settings = Settings()