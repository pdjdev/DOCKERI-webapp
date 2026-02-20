# KERI 현장실습 프로젝트: DOCKERI
<img width="1311" height="805" alt="image" src="https://github.com/user-attachments/assets/bf802971-e176-48ab-a9f8-d05142bc39a2" />

**전기 기술 문서 분석 및 계산 AI 에이전트 개발**

---

## 프로젝트 개요

### 프로젝트 명칭
DOCKERI - 전기 기술 문서 분석 및 계산 AI 에이전트

### 실습 기간
2025년 겨울학기 (2026.01~2026.02)

### 실습 기관
KERI (한국전기연구원)

### 프로젝트 목적
복잡한 전기 기술 문서를 AI 기반으로 분석하고, 사용자 질문에 맞춤형 답변을 제공하며, 정교한 수식 계산까지 수행하는 지능형 에이전트 시스템 개발


---

## 환경 구축 및 실행

Windows 기준으로 설명되었습니다.

### 서버 환경 구축

아래의 명령을 `server` 폴더 내에서 수행합니다.

```batch
REM Git 설치 및 LFS 활성화
winget install --id Git.Git -e --source winget
git lfs install

REM 임베딩 모델 다운로드
git clone https://huggingface.co/BAAI/bge-m3

REM 필요 패키지 설치
setup.cmd
```

설치 완료 후, `.env` 파일을 만들고 아래처럼 환경 변수를 설정합니다.

* Gemini API 키는 필수이며, 나머지 설정은 미선언시 기본값으로 자동 설정됩니다.

```env
# DOCKERI API Server 환경 설정

# 필수: Gemini API 키
GEMINI_API_KEY=your_gemini_api_key_here

# 서버 설정
HOST=0.0.0.0
PORT=8000

# 태스크 관리
TASK_RETENTION_DAYS=7

# LLM 설정  
LLM_MODEL=gemini-2.5-flash

# 벡터 검색 설정
RETRIEVAL_K=4
CHUNK_SIZE=1000  
CHUNK_OVERLAP=100
```

환경 변수 작성이 완료되었다면, 아래처럼 서버를 시작합니다.
```batch
run.cmd
```

### 클라이언트 환경 구축

아래의 명령을 `client` 폴더 내에서 수행합니다.

```batch
setup.cmd
```

