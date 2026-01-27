import os
import shutil
import hashlib
import traceback
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from pydantic import BaseModel
from dotenv import load_dotenv

# LangChain 관련 임포트
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
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

# --- Pydantic 모델 (요청/응답 스키마) ---
class ChatRequest(BaseModel):
    query: str

class SourceDocument(BaseModel):
    source: str
    content: str

class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceDocument]

class DocumentListResponse(BaseModel):
    count: int
    documents: List[str]

# --- 핵심 로직 클래스 ---
class RAGManager:
    def __init__(self):
        self.embeddings = None
        self.vectorstore = None
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
                self.setup_chain()
                print("벡터 DB 및 체인 로드 완료.")
            except Exception as e:
                print(f"DB 로드 실패 (초기화 필요): {e}")
                self.vectorstore = None
        else:
            print("기존 벡터 DB가 없습니다. 문서 업로드가 필요합니다.")
            self.vectorstore = None

    def setup_chain(self):
        """RAG 체인 구성"""
        if not self.vectorstore:
            return

        retriever = self.vectorstore.as_retriever(search_kwargs={"k": 5})
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1, thinking_budget=0)

        system_prompt = (
            "당신은 기술 지원 전문가입니다. 아래 제공된 [참고 문서] 내용만을 바탕으로 답변하세요. "
            "문서에 내용이 없다면 '해당 내용은 문서에서 찾을 수 없습니다'라고 답변하세요.\n\n"
            "[참고 문서]\n{context}"
        )
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])

        question_answer_chain = create_stuff_documents_chain(llm, prompt)
        self.rag_chain = create_retrieval_chain(retriever, question_answer_chain)

    def ingest_documents(self):
        """문서 폴더 스캔 및 DB 업데이트 (ingest.py 로직 통합)"""
        print("문서 처리 시작...")
        
        # 1. 기존 해시 로드
        existing_hashes = set()
        if self.vectorstore:
            for doc_id, doc in self.vectorstore.docstore._dict.items():
                if 'file_hash' in doc.metadata:
                    existing_hashes.add(doc.metadata['file_hash'])

        # 2. 신규 파일 탐색
        all_pdf_files = [f for f in os.listdir(DATA_PATH) if f.lower().endswith('.pdf')]
        files_to_process = []

        for file in all_pdf_files:
            file_path = os.path.join(DATA_PATH, file)
            # 해시 계산
            hash_sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            f_hash = hash_sha256.hexdigest()
            
            if f_hash not in existing_hashes:
                files_to_process.append((file, f_hash))

        if not files_to_process:
            return "변경된 문서가 없습니다."

        # 3. 문서 로드 및 분할
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
            
            # 중요: 체인 재설정 (retriever 갱신을 위해)
            self.setup_chain()
            
            return f"{len(files_to_process)}개의 파일, {len(texts)}개의 청크가 추가되었습니다."
        
        return "처리할 텍스트가 없습니다."

    def delete_document(self, filename: str):
        """특정 문서 삭제 및 DB 저장"""
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
        
        # 체인 재설정
        self.setup_chain()
        return True

    def get_document_list(self):
        """현재 DB에 저장된 문서 목록 반환"""
        if not self.vectorstore:
            return []
        
        sources = set()
        doc_dict = self.vectorstore.docstore._dict
        for doc_id in doc_dict:
            metadata = doc_dict[doc_id].metadata
            if 'source' in metadata:
                sources.add(os.path.basename(metadata['source']))
        return sorted(list(sources))

# --- FastAPI 앱 설정 ---
app = FastAPI(title="DOC-KERI API")

# 전역 매니저 인스턴스 (앱 시작 시 로드됨)
rag_manager = RAGManager()

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    질문을 받아 RAG 기반 답변을 반환합니다.
    """
    if not rag_manager.rag_chain:
        raise HTTPException(status_code=503, detail="시스템이 아직 초기화되지 않았거나 문서가 없습니다.")

    try:
        response = await rag_manager.rag_chain.ainvoke({"input": request.query})
        
        sources = []
        for doc in response.get('context', []):
            sources.append(SourceDocument(
                source=os.path.basename(doc.metadata.get('source', '알 수 없음')),
                content=doc.page_content[:200]  # 미리보기용으로 일부만 전송
            ))
            
        return ChatResponse(
            answer=response['answer'],
            sources=sources
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """
    PDF 파일을 업로드하고 백그라운드에서 벡터 DB 처리를 시작합니다.
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능합니다.")

    file_location = os.path.join(DATA_PATH, file.filename)
    
    try:
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파일 저장 실패: {str(e)}")

    # 파일 저장이 완료되면 문서 처리를 수행
    result_msg = rag_manager.ingest_documents()
    
    return {"message": f"파일 '{file.filename}' 업로드 완료. DB 처리 결과: {result_msg}"}

@app.post("/ingest")
async def trigger_ingest():
    """
    docs 폴더를 수동으로 스캔하여 DB를 업데이트합니다.
    """
    try:
        result = rag_manager.ingest_documents()
        return {"message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents", response_model=DocumentListResponse)
async def list_documents():
    """
    현재 벡터 DB에 색인된 문서 목록을 반환합니다.
    """
    docs = rag_manager.get_document_list()
    return DocumentListResponse(count=len(docs), documents=docs)

@app.delete("/documents") 
async def delete_document(filename: str): # 함수의 인자로 선언하면 자동으로 Query Parameter로 인식합니다.
    """
    특정 문서를 벡터 DB와 디스크에서 삭제합니다.
    요청 URL 예시: DELETE /documents?filename=example.pdf
    """
    # 1. DB에서 삭제
    db_deleted = rag_manager.delete_document(filename)
    
    # 2. 실제 파일 삭제
    file_path = os.path.join(DATA_PATH, filename)
    file_deleted = False
    if os.path.exists(file_path):
        os.remove(file_path)
        file_deleted = True
    
    if not db_deleted and not file_deleted:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
        
    return {
        "message": "삭제 완료",
        "db_deleted": db_deleted,
        "file_deleted": file_deleted
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)