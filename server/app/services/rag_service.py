"""
RAG (Retrieval-Augmented Generation) 서비스
"""
import os
import re
import hashlib
import shutil
import time
from typing import Optional, Callable, List

# LangChain 관련 임포트
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.document_loaders import PyMuPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings


class RAGService:
    """RAG(Retrieval-Augmented Generation) 핵심 서비스"""
    
    def __init__(self):
        self.embeddings = None
        self.vectorstore = None
        self.retriever = None
        # 초기화 시 모델 로드
        self.load_resources()

    def load_resources(self):
        """임베딩 모델 및 벡터 DB 로드"""
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
        
        print(f"시스템 초기화: {device} 장치 사용 중...")
        
        # 임베딩 모델 로드 (시간이 걸릴 수 있음)
        self.embeddings = HuggingFaceEmbeddings(
            model_name=settings.MODEL_PATH,
            model_kwargs={'device': device},
            encode_kwargs={'normalize_embeddings': True}
        )

        if os.path.exists(settings.DB_PATH):
            try:
                self.vectorstore = FAISS.load_local(
                    settings.DB_PATH, 
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
            self.retriever = self.vectorstore.as_retriever(
                search_kwargs={"k": settings.RETRIEVAL_K}
            )

    def ingest_documents(
        self, 
        target_filename: Optional[str] = None, 
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> str:
        """
        문서 폴더 스캔 및 DB 업데이트 (PDF 및 Markdown 지원)
        
        Args:
            target_filename: 특정 파일만 처리하고 싶을 때 파일명 지정 (없으면 전체 스캔)
            progress_callback: 진행률(%)과 메시지를 전달할 콜백 함수
            
        Returns:
            처리 결과 메시지
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

        # 2. 처리할 파일 식별 (.pdf 및 .md 파일 검색)
        allowed_extensions = ('.pdf', '.md')
        all_files = [
            f for f in os.listdir(settings.DATA_PATH) 
            if f.lower().endswith(allowed_extensions)
        ]
        
        # 특정 파일만 지정된 경우 필터링 (업로드 직후 로직 최적화)
        if target_filename:
            if target_filename in all_files:
                all_files = [target_filename]
            else:
                report(100, "파일을 찾을 수 없습니다.")
                return "파일을 찾을 수 없습니다."

        files_to_process = []
        
        # 해시 체크 (약 0~10% 구간 할당)
        total_scan = len(all_files)
        for idx, file in enumerate(all_files):
            file_path = os.path.join(settings.DATA_PATH, file)
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
        
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE, 
            chunk_overlap=settings.CHUNK_OVERLAP
        )

        for idx, (file, f_hash) in enumerate(files_to_process):
            report(10 + int((idx / total_files) * 10), f"문서 읽는 중: {file}")
            file_path = os.path.join(settings.DATA_PATH, file)
            
            try:
                # 확장자에 따른 로더 분기 처리
                if file.lower().endswith('.pdf'):
                    loader = PyMuPDFLoader(file_path)
                elif file.lower().endswith('.md'):
                    # 마크다운은 TextLoader 사용 (UTF-8 인코딩 지정)
                    loader = TextLoader(file_path, encoding='utf-8')
                else:
                    # 이론상 오지 않음 (위에서 필터링함)
                    continue

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
                time.sleep(0.01)

        # 5. 저장 및 마무리 (90~100%)
        report(95, "데이터베이스 저장 중...")
        self.vectorstore.save_local(settings.DB_PATH)
        self.setup_retriever() # 리트리버 갱신
        
        report(100, "완료")
        return f"{len(files_to_process)}개의 파일, {len(new_texts)}개의 청크가 처리되었습니다."

    def delete_document(self, filename: str) -> bool:
        """
        문서 삭제 (벡터 DB + docs/imgs/{doc_name}/ 이미지 폴더 포함)
        
        Args:
            filename: 삭제할 파일명 (예: "my_doc.md" 또는 "my_doc.pdf")
            
        Returns:
            삭제 성공 여부
        """
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
        self.vectorstore.save_local(settings.DB_PATH)
        self.setup_retriever()

        # ZIP 문서(md)에서 추출된 이미지 폴더도 삭제
        doc_name = os.path.splitext(filename)[0]
        imgs_dir = os.path.join(settings.IMGS_PATH, doc_name)
        if os.path.isdir(imgs_dir):
            try:
                shutil.rmtree(imgs_dir)
                print(f"[삭제] 이미지 폴더 제거: {imgs_dir}")
            except Exception as e:
                print(f"[경고] 이미지 폴더 삭제 실패 ({imgs_dir}): {e}")

        return True

    def get_document_list(self) -> List[str]:
        """
        저장된 문서 목록 반환
        
        Returns:
            문서 파일명 리스트
        """
        if not self.vectorstore:
            return []
        sources = set()
        doc_dict = self.vectorstore.docstore._dict
        for doc_id in doc_dict:
            metadata = doc_dict[doc_id].metadata
            if 'source' in metadata:
                sources.add(os.path.basename(metadata['source']))
        return sorted(list(sources))