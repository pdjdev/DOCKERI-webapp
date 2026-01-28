import os
import shutil
import hashlib
import traceback
import json
import asyncio
from typing import List, Optional, Dict, Any

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
MODEL_PATH = './bge-m3'
DB_PATH = 'vectorstore/db_faiss'
DATA_PATH = './docs'

# 디렉토리 자동 생성
os.makedirs(DATA_PATH, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

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
            # 문서가 없을 경우를 대비한 깡통 체인 (LLM만 사용하거나 에러 반환 가능)
            # 여기서는 편의상 에러 대신 일반 LLM 대화로 넘어가거나 예외 처리
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

    def ingest_documents(self):
        """문서 폴더 스캔 및 DB 업데이트"""
        print("문서 처리 시작...")
        
        existing_hashes = set()
        if self.vectorstore:
            for doc_id, doc in self.vectorstore.docstore._dict.items():
                if 'file_hash' in doc.metadata:
                    existing_hashes.add(doc.metadata['file_hash'])

        all_pdf_files = [f for f in os.listdir(DATA_PATH) if f.lower().endswith('.pdf')]
        files_to_process = []

        for file in all_pdf_files:
            file_path = os.path.join(DATA_PATH, file)
            hash_sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            f_hash = hash_sha256.hexdigest()
            
            if f_hash not in existing_hashes:
                files_to_process.append((file, f_hash))

        if not files_to_process:
            return "변경된 문서가 없습니다."

        new_documents = []
        for file, f_hash in files_to_process:
            try:
                loader = PyMuPDFLoader(os.path.join(DATA_PATH, file))
                docs = loader.load()
                for d in docs:
                    d.metadata['file_hash'] = f_hash
                    d.metadata['source'] = file
                new_documents.extend(docs)
            except Exception as e:
                print(f"파일 로드 오류 ({file}): {e}")

        if new_documents:
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
            texts = text_splitter.split_documents(new_documents)

            if self.vectorstore:
                self.vectorstore.add_documents(texts)
            else:
                self.vectorstore = FAISS.from_documents(texts, self.embeddings)
            
            self.vectorstore.save_local(DB_PATH)
            self.setup_retriever() # 리트리버 갱신
            
            return f"{len(files_to_process)}개의 파일, {len(texts)}개의 청크가 추가되었습니다."
        
        return "처리할 텍스트가 없습니다."

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
    """PDF 파일 업로드 및 처리"""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능합니다.")

    file_location = os.path.join(DATA_PATH, file.filename)
    try:
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파일 저장 실패: {str(e)}")

    result_msg = rag_manager.ingest_documents()
    return {"message": f"파일 '{file.filename}' 업로드 완료. {result_msg}"}

@app.post("/ingest")
async def trigger_ingest():
    try:
        result = rag_manager.ingest_documents()
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