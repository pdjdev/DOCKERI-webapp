import os
import shutil
import hashlib
import traceback
import json
import asyncio
import yaml
from typing import List, Optional, Dict, Any, Callable
from datetime import datetime, timedelta
import time
import uuid

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# LangChain 관련 임포트
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableSerializable
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# --- 설정 및 상수 ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_PATH = './bge-m3'  # 로컬 모델 경로 또는 HuggingFace ID
DB_PATH = 'vectorstore/db_faiss'
DATA_PATH = './docs'

# 디렉토리 자동 생성
os.makedirs(DATA_PATH, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# 태스크 상태 파일 (영속화)
TASKS_FILE = os.path.join(os.path.dirname(__file__), "upload_tasks.yaml")
TASK_RETENTION_DAYS = int(os.getenv("TASK_RETENTION_DAYS", "7"))

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY가 .env 파일에 정의되어 있지 않습니다.")

# --- Pydantic 모델 (구조화된 입력 지원) ---
class Part(BaseModel):
    text: str

class Content(BaseModel):
    role: str
    parts: List[Part]

class ChatRequest(BaseModel):
    # Gemini API 스타일의 구조화된 입력 (대화 히스토리 포함)
    contents: List[Content]
    
    # 선택적 설정
    temperature: float = 0.1

class DocumentListResponse(BaseModel):
    count: int
    documents: List[str]

# --- 핵심 로직 클래스 ---
class RAGManager:
    def __init__(self):
        self.embeddings = None
        self.vectorstore = None
        self.retriever = None
        self.rag_chain = None
        # 초기화 시 모델 로드
        self.load_resources()

    def load_resources(self):
        """임베딩 모델 및 벡터 DB 로드"""
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        print(f"시스템 초기화: {device} 장치 사용 중...")
        
        # 임베딩 모델 로드 (시간이 걸릴 수 있음)
        self.embeddings = HuggingFaceEmbeddings(
            model_name=MODEL_PATH,
            model_kwargs={'device': device},
            encode_kwargs={'normalize_embeddings': True}
        )

        if os.path.exists(DB_PATH):
            try:
                self.vectorstore = FAISS.load_local(
                    DB_PATH, 
                    self.embeddings, 
                    allow_dangerous_deserialization=True 
                )
                self.setup_retriever()
                print("벡터 DB 로드 완료.")
            except Exception as e:
                print(f"DB 로드 실패 (초기화 필요): {e}")
                self.vectorstore = None
        else:
            print("기존 벡터 DB가 없습니다. 문서 업로드가 필요합니다.")
            self.vectorstore = None

    def setup_retriever(self):
        """Retriever 설정"""
        if self.vectorstore:
            self.retriever = self.vectorstore.as_retriever(search_kwargs={"k": 4})

    def get_chain(self, temperature=0.1):
        """
        LCEL(LangChain Expression Language)을 사용하여 체인을 동적으로 생성
        스트리밍과 히스토리 처리에 최적화됨
        """
        if not self.retriever:
            return None

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash", 
            temperature=temperature, 
            streaming=True # 스트리밍 활성화
        )

        # 시스템 프롬프트 (Context 포함)
        system_template = (
            "당신은 전문 기술 지원 AI입니다. 아래 제공된 [참고 문서]를 바탕으로 답변하세요.\n"
            "문서 내용을 기반으로 답변하되, 문서에 없는 내용은 '문서에서 찾을 수 없습니다'라고 하세요.\n"
            "이전 대화 맥락을 고려하여 자연스럽게 답변하세요.\n\n"
            "[참고 문서]\n{context}"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_template),
            MessagesPlaceholder(variable_name="history"), # 대화 히스토리 삽입 지점
            ("human", "{question}"),
        ])

        def format_docs(docs):
            return "\n\n".join(doc.page_content for doc in docs)

        # RAG 체인 구성 (Retriever -> Format -> Prompt -> LLM -> Parser)
        chain = (
            {
                "context": self.retriever | format_docs,
                "question": RunnablePassthrough(),
                "history": RunnablePassthrough() 
            }
            | prompt
            | llm
            | StrOutputParser()
        )
        
        return chain

    def ingest_documents(self, target_filename: Optional[str] = None, progress_callback: Optional[Callable[[int, str], None]] = None):
        """
        문서 폴더 스캔 및 DB 업데이트
        
        Args:
            target_filename: 특정 파일만 처리하고 싶을 때 파일명 지정 (없으면 전체 스캔)
            progress_callback: 진행률(%)과 메시지를 전달할 콜백 함수
        """
        def report(pct: int, msg: str):
            try:
                if progress_callback:
                    progress_callback(pct, msg)
                # 디버깅용 로그
                print(f"[Progress {pct}%] {msg}")
            except Exception:
                pass

        report(0, "문서 분석 준비 중...")

        # 1. 기존 DB 해시 로드
        existing_hashes = set()
        if self.vectorstore:
            try:
                for doc_id, doc in self.vectorstore.docstore._dict.items():
                    if 'file_hash' in doc.metadata:
                        existing_hashes.add(doc.metadata['file_hash'])
            except Exception:
                pass # 인덱스가 비어있거나 접근 불가 시 무시

        # 2. 처리할 파일 식별
        all_pdf_files = [f for f in os.listdir(DATA_PATH) if f.lower().endswith('.pdf')]
        
        # 특정 파일만 지정된 경우 필터링 (업로드 직후 로직 최적화)
        if target_filename:
            if target_filename in all_pdf_files:
                all_pdf_files = [target_filename]
            else:
                report(100, "파일을 찾을 수 없습니다.")
                return "파일을 찾을 수 없습니다."

        files_to_process = []
        
        # 해시 체크 (약 0~10% 구간 할당)
        total_scan = len(all_pdf_files)
        for idx, file in enumerate(all_pdf_files):
            file_path = os.path.join(DATA_PATH, file)
            hash_sha256 = hashlib.sha256()
            try:
                with open(file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        hash_sha256.update(chunk)
                f_hash = hash_sha256.hexdigest()
                
                # 해시가 없으면(새 파일) 처리 대상에 추가
                if f_hash not in existing_hashes:
                    files_to_process.append((file, f_hash))
            except Exception as e:
                print(f"해시 계산 오류 {file}: {e}")
            
            # 해시 체크 진행률 (최대 10%까지)
            if total_scan > 0:
                p = int((idx + 1) / total_scan * 10)
                report(p, "파일 변경 사항 확인 중...")

        if not files_to_process:
            report(100, "변경된 문서가 없습니다.")
            return "변경된 문서가 없습니다."

        # 3. 문서 로드 및 분할 (10~30% 구간 할당)
        new_texts = []
        total_files = len(files_to_process)
        
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

        for idx, (file, f_hash) in enumerate(files_to_process):
            report(10 + int((idx / total_files) * 10), f"문서 읽는 중: {file}")
            try:
                loader = PyMuPDFLoader(os.path.join(DATA_PATH, file))
                docs = loader.load()
                
                # 메타데이터 주입
                for d in docs:
                    d.metadata['file_hash'] = f_hash
                    d.metadata['source'] = file
                
                # 분할
                splits = text_splitter.split_documents(docs)
                new_texts.extend(splits)
                
            except Exception as e:
                print(f"파일 로드 오류 ({file}): {e}")
                report(20, f"오류 발생: {file}")

        if not new_texts:
            report(100, "추출된 텍스트가 없습니다.")
            return "추출된 텍스트가 없습니다."

        report(30, f"총 {len(new_texts)}개의 텍스트 청크 생성됨. 임베딩 시작...")

        # 4. 임베딩 및 벡터 저장 (30~90% 구간 할당) - 여기가 핵심 병목 구간
        # 한 번에 넣지 않고 배치로 나누어 진행률을 업데이트함
        
        BATCH_SIZE = 4  # 한 번에 처리할 청크 개수 (GPU 메모리나 API 제한에 따라 조절)
        total_chunks = len(new_texts)
        
        # FAISS 인스턴스가 없으면 첫 배치로 생성
        if self.vectorstore is None:
            first_batch = new_texts[:BATCH_SIZE]
            remaining_texts = new_texts[BATCH_SIZE:]
            
            report(30, "벡터 데이터베이스 초기화 중...")
            self.vectorstore = FAISS.from_documents(first_batch, self.embeddings)
            processed_count = len(first_batch)
        else:
            remaining_texts = new_texts
            processed_count = 0

        # 나머지 배치 처리
        for i in range(0, len(remaining_texts), BATCH_SIZE):
            batch = remaining_texts[i : i + BATCH_SIZE]
            if batch:
                self.vectorstore.add_documents(batch)
                
                processed_count += len(batch)
                
                # 진행률 계산 (30%에서 90% 사이로 매핑)
                # progress = 30 + (처리된 수 / 전체 수) * 60
                progress = 30 + int((processed_count / total_chunks) * 60)
                report(progress, f"지식 데이터베이스 구축 중... ({processed_count}/{total_chunks})")
                
                # CPU/GPU 숨 돌리기 (선택 사항)
                # await는 async 함수 내에서만 사용 가능하므로 time.sleep 사용
                time.sleep(0.01)

        # 5. 저장 및 마무리 (90~100%)
        report(95, "데이터베이스 저장 중...")
        self.vectorstore.save_local(DB_PATH)
        self.setup_retriever() # 리트리버 갱신
        
        report(100, "완료")
        return f"{len(files_to_process)}개의 파일, {len(new_texts)}개의 청크가 처리되었습니다."

    def delete_document(self, filename: str):
        if not self.vectorstore:
            return False
        doc_dict = self.vectorstore.docstore._dict
        ids_to_delete = [
            doc_id for doc_id, doc in doc_dict.items()
            if os.path.basename(doc.metadata.get('source', '')) == filename
        ]
        if not ids_to_delete:
            return False
        self.vectorstore.delete(ids_to_delete)
        self.vectorstore.save_local(DB_PATH)
        self.setup_retriever()
        return True

    def get_document_list(self):
        if not self.vectorstore:
            return []
        sources = set()
        doc_dict = self.vectorstore.docstore._dict
        for doc_id in doc_dict:
            metadata = doc_dict[doc_id].metadata
            if 'source' in metadata:
                sources.add(os.path.basename(metadata['source']))
        return sorted(list(sources))

# --- 유틸리티 함수 ---
def parse_history(contents: List[Content]) -> tuple[str, List[BaseMessage]]:
    """
    JSON 입력(contents)을 파싱하여:
    1. 최신 질문 (last_query)
    2. LangChain 형식의 대화 히스토리 (history_messages)
    로 분리합니다.
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

# --- FastAPI 앱 설정 ---
app = FastAPI(title="DOC-KERI API (Streaming)")
rag_manager = RAGManager()

# 업로드 처리 상태 저장소
upload_tasks: Dict[str, Dict[str, Any]] = {}
upload_tasks_lock = asyncio.Lock()

def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

async def save_tasks_to_file():
    try:
        async with upload_tasks_lock:
            data = {k: v for k, v in upload_tasks.items()}
        # 파일 쓰기는 스레드에서 수행
        await asyncio.to_thread(lambda: yaml.safe_dump(data, open(TASKS_FILE, "w", encoding="utf-8")))
    except Exception as e:
        print(f"작업 파일 저장 실패: {e}")

async def load_tasks_from_file():
    try:
        if os.path.exists(TASKS_FILE):
            def _load():
                with open(TASKS_FILE, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            data = await asyncio.to_thread(_load)
            async with upload_tasks_lock:
                upload_tasks.clear()
                for k, v in data.items():
                    upload_tasks[k] = v
    except Exception as e:
        print(f"작업 파일 로드 실패: {e}")

async def process_uploaded_file(task_id: str, filename: str):
    """백그라운드에서 문서 분석을 수행하고 상태를 갱신합니다."""
    async with upload_tasks_lock:
        upload_tasks[task_id] = {
            "status": "processing",
            "message": "처리 시작",
            "filename": filename,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "progress": 0,
        }
    await save_tasks_to_file()

    # 메인 스레드의 이벤트 루프 캡처 (스레드에서 콜백 시 사용)
    loop = asyncio.get_running_loop()

    def progress_cb(pct: int, msg: str):
        # 비동기 함수 내에서 동기 콜백이 호출되므로, 
        # 이벤트 루프에 안전하게 작업을 예약해야 함
        async def _update():
            async with upload_tasks_lock:
                if task_id in upload_tasks:
                    t = upload_tasks[task_id]
                    # 진행률이 뒤로 가는 것을 방지
                    current_prog = t.get("progress", 0)
                    new_prog = max(0, min(100, int(pct)))
                    if new_prog >= current_prog:
                        t["progress"] = new_prog
                        t["message"] = msg
                        t["updated_at"] = _now_iso()
                        upload_tasks[task_id] = t
            await save_tasks_to_file()
            
        # 스레드 안전하게 메인 루프에 코루틴 예약
        asyncio.run_coroutine_threadsafe(_update(), loop)

    try:
        # target_filename 인자를 전달하여 해당 파일만 즉시 처리하도록 최적화
        # async 함수 내부에서 호출되므로 await 사용 가능하도록 구조 변경 고려했으나,
        # ingest_documents 자체가 동기 함수이므로 to_thread 유지
        result = await asyncio.to_thread(
            rag_manager.ingest_documents, 
            target_filename=filename, 
            progress_callback=progress_cb
        )
        
        async with upload_tasks_lock:
            upload_tasks[task_id]["status"] = "done"
            upload_tasks[task_id]["message"] = str(result)
            upload_tasks[task_id]["progress"] = 100
            upload_tasks[task_id]["updated_at"] = _now_iso()
        await save_tasks_to_file()
        
    except Exception as e:
        async with upload_tasks_lock:
            upload_tasks[task_id]["status"] = "failed"
            upload_tasks[task_id]["message"] = str(e)
            upload_tasks[task_id]["updated_at"] = _now_iso()
        await save_tasks_to_file()
        print(f"처리 중 에러 발생: {e}")
        traceback.print_exc()

@app.post("/chat")
async def chat_stream_endpoint(request: ChatRequest):
    """
    구조화된 대화 이력을 받아 스트리밍 응답을 제공합니다.
    """
    # 1. 시스템 준비 확인
    if not rag_manager.retriever:
        raise HTTPException(status_code=503, detail="시스템 초기화 전이거나 문서가 없습니다.")

    # 2. 입력 파싱 (질문과 히스토리 분리)
    current_query, history = parse_history(request.contents)
    
    if not current_query:
        raise HTTPException(status_code=400, detail="질문 내용이 없습니다.")

    # 3. 문서 검색 (Sources 확보를 위해 미리 수행)
    # 스트리밍 중에 retriever를 돌리면 source 정보를 따로 빼내기 복잡하므로 미리 수행
    retrieved_docs = await rag_manager.retriever.ainvoke(current_query)
    
    # 4. 체인 준비 (retriever 대신 이미 찾은 doc string을 주입하는 방식도 가능하지만, 
    # 여기서는 검색된 doc을 context로 포매팅하여 직접 프롬프트에 넣는 방식으로 구성)
    
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash", 
        temperature=request.temperature, 
        streaming=True
    )
    
    context_text = "\n\n".join(doc.page_content for doc in retrieved_docs)
    
    system_prompt = (
        "당신은 기술 지원 전문가입니다. 아래 제공된 [참고 문서] 내용만을 바탕으로 답변하세요. "
        "문서에 내용이 없다면 '해당 내용은 문서에서 찾을 수 없습니다'라고 답변하세요.\n\n"
        "[참고 문서]\n{context}"
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{question}"),
    ])
    
    # Context를 미리 주입한 체인 생성
    chain = prompt | llm | StrOutputParser()

    # 5. 비동기 제너레이터 함수 정의
    async def response_generator():
        try:
            # (1) 답변 스트리밍
            async for chunk in chain.astream({
                "context": context_text,
                "history": history,
                "question": current_query
            }):
                yield chunk # 텍스트 조각 전송

            # (2) 답변 완료 후 출처 정보 전송 (선택 사항)
            # 클라이언트가 텍스트만 쭉 찍어도 보기 좋게 줄바꿈 후 출처 표기
            if retrieved_docs:
                unique_sources = sorted(list(set(
                    os.path.basename(doc.metadata.get('source', 'Unknown')) 
                    for doc in retrieved_docs
                )))
                sources_text = "\n\n---\n**참고 문헌:**\n" + "\n".join(f"- {s}" for s in unique_sources)
                yield sources_text

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

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """PDF 파일 업로드: 파일 저장 후 바로 응답하고 백그라운드에서 처리 시작"""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능합니다.")

    file_location = os.path.join(DATA_PATH, file.filename)
    try:
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파일 저장 실패: {str(e)}")

    task_id = str(uuid.uuid4())
    async with upload_tasks_lock:
        upload_tasks[task_id] = {
            "status": "uploaded",
            "message": "파일 업로드 완료, 큐에 등록됨",
            "filename": file.filename,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "progress": 0,
        }

    # 백그라운드로 처리 시작 (이 함수는 논블로킹)
    asyncio.create_task(process_uploaded_file(task_id, file.filename))

    return {"task_id": task_id, "message": f"파일 '{file.filename}' 업로드 완료. 처리 시작됨"}


@app.get("/upload/status/{task_id}")
async def upload_status(task_id: str):
    """업로드 및 처리 상태를 폴링하기 위한 엔드포인트"""
    async with upload_tasks_lock:
        info = upload_tasks.get(task_id)
    if not info:
        raise HTTPException(status_code=404, detail="해당 task_id를 찾을 수 없습니다.")
    return {"task_id": task_id, **info}


@app.get("/upload/tasks")
async def list_upload_tasks():
    """모든 업로드 태스크 목록 반환"""
    async with upload_tasks_lock:
        data = {k: v for k, v in upload_tasks.items()}
    return data


async def _cleanup_loop():
    """오래된 태스크를 정리하고 주기적으로 파일에 저장"""
    while True:
        try:
            cutoff = datetime.utcnow() - timedelta(days=TASK_RETENTION_DAYS)
            cutoff_iso = cutoff.isoformat() + "Z"
            removed = []
            async with upload_tasks_lock:
                for k, v in list(upload_tasks.items()):
                    created = v.get("created_at")
                    if created and created < cutoff_iso:
                        removed.append(k)
                        del upload_tasks[k]
            if removed:
                await save_tasks_to_file()
                print(f"정리된 태스크: {removed}")
        except Exception as e:
            print(f"정리 작업 중 오류: {e}")
        await asyncio.sleep(60 * 60)  # 1시간 간격


@app.on_event("startup")
async def startup_tasks():
    await load_tasks_from_file()
    # 백그라운드 정리 데몬 시작
    asyncio.create_task(_cleanup_loop())

@app.post("/ingest")
async def trigger_ingest():
    """
    수동으로 전체 문서 재처리를 요청할 때 사용
    (파일 업로드 흐름이 아니라 전체 docs 폴더를 다시 스캔하고 싶을 때)
    """
    try:
        # 이 엔드포인트는 동기로 기다림 (오래 걸릴 수 있음 주의)
        # 필요하다면 백그라운드 태스크로 전환 가능
        result = await asyncio.to_thread(rag_manager.ingest_documents)
        return {"message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents", response_model=DocumentListResponse)
async def list_documents():
    docs = rag_manager.get_document_list()
    return DocumentListResponse(count=len(docs), documents=docs)

@app.delete("/documents") 
async def delete_document_endpoint(filename: str):
    db_deleted = rag_manager.delete_document(filename)
    file_path = os.path.join(DATA_PATH, filename)
    file_deleted = False
    if os.path.exists(file_path):
        os.remove(file_path)
        file_deleted = True
    
    if not db_deleted and not file_deleted:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
        
    return {"message": "삭제 완료", "db_deleted": db_deleted, "file_deleted": file_deleted}

if __name__ == "__main__":
    import uvicorn
    # uvicorn 실행 시 access_log=False 등을 추가하여 콘솔 출력을 줄일 수 있습니다.
    uvicorn.run(app, host="0.0.0.0", port=8000)