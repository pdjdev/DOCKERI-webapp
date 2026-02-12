# DOCKERI Server

전기 기술 문서 RAG (Retrieval-Augmented Generation) 시스템 FastAPI 백엔드 서버

## 시작

### 1. 환경 설정

```bash
# 1단계: 가상환경 생성 및 패키지 설치
./setup.cmd

# 2단계: 환경변수 설정
cp .env.example .env
# .env 파일에서 GEMINI_API_KEY 설정 필요
```

### 2. 서버 실행

**Windows (PowerShell):**
```powershell
./run_server.ps1
```

**Windows (CMD):**
```cmd
run.cmd
```

**수동 실행:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 프로젝트 구조

```
server/
├── app/                        # API 앱 루트
│   ├── main.py                 # 진입점
│   ├── config/
│   │   └── settings.py         # 설정 관리
│   ├── models/
│   │   └── schemas.py          # Pydantic 스키마
│   ├── services/
│   │   ├── rag_service.py      # RAG 핵심 로직
│   │   └── upload_service.py   # 업로드 처리
│   ├── utils/
│   │   ├── code_execution.py   # Python 코드 실행
│   │   └── response_processing.py
│   └── api/v1/
│       ├── api.py              # 라우터 통합
│       └── endpoints/          # API 엔드포인트들
├── docs/                       # 업로드된 문서들
├── vectorstore/                # FAISS 벡터 DB
└── bge-m3/                     # 임베딩 모델
```

## API 엔드포인트

### 채팅
- `POST /chat` - 스트리밍 채팅 응답

### 파일 업로드
- `POST /upload` - 문서 업로드 (PDF/MD)
- `GET /upload/status/{task_id}` - 처리 상태 확인
- `GET /upload/tasks` - 모든 업로드 태스크 목록

### 문서 관리  
- `GET /documents` - 저장된 문서 목록
- `POST /documents/ingest` - 전체 문서 재처리
- `DELETE /documents?filename=xxx` - 문서 삭제

### 시스템
- `GET /` - 루트 (헬스체크)
- `GET /health` - 상세 헬스체크

## 환경 변수

```bash
# 필수 설정
GEMINI_API_KEY=your_gemini_api_key_here

# 선택적 설정
HOST=0.0.0.0
PORT=8000
TASK_RETENTION_DAYS=7
RETRIEVAL_K=4
CHUNK_SIZE=1000
CHUNK_OVERLAP=100
LLM_MODEL=gemini-2.5-flash
```

## 주요 엔드포인트

1. **문서 업로드**: `/upload` 엔드포인트로 PDF/MD 파일 업로드
2. **처리 상태 확인**: `/upload/status/{task_id}`로 진행률 모니터링
3. **채팅**: `/chat` 엔드포인트로 문서 기반 질의응답
4. **문서 관리**: `/documents` 엔드포인트로 저장된 문서 조회/삭제

## 개발 정보

- **Framework**: FastAPI 0.104+
- **LLM**: Google Gemini 2.5 Flash
- **Embeddings**: BGE-M3 (로컬)
- **Vector Store**: FAISS
- **Document Loaders**: PyMuPDF, TextLoader
