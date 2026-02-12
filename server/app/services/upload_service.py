"""
파일 업로드 및 백그라운드 처리 서비스
"""
import os
import asyncio
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any
import yaml

from app.config import settings


class UploadService:
    """파일 업로드 및 백그라운드 처리 관리 서비스"""
    
    def __init__(self):
        self.upload_tasks: Dict[str, Dict[str, Any]] = {}
        self.upload_tasks_lock = asyncio.Lock()
        
    def _now_iso(self) -> str:
        """현재 시간을 ISO 형식으로 반환"""
        return datetime.utcnow().isoformat() + "Z"

    async def save_tasks_to_file(self):
        """태스크 상태를 파일에 영속화"""
        try:
            async with self.upload_tasks_lock:
                data = {k: v for k, v in self.upload_tasks.items()}
            # 파일 쓰기는 스레드에서 수행
            await asyncio.to_thread(
                lambda: yaml.safe_dump(data, open(settings.TASKS_FILE, "w", encoding="utf-8"))
            )
        except Exception as e:
            print(f"작업 파일 저장 실패: {e}")

    async def load_tasks_from_file(self):
        """파일에서 태스크 상태 복원"""
        try:
            if os.path.exists(settings.TASKS_FILE):
                def _load():
                    with open(settings.TASKS_FILE, "r", encoding="utf-8") as f:
                        return yaml.safe_load(f) or {}
                data = await asyncio.to_thread(_load)
                async with self.upload_tasks_lock:
                    self.upload_tasks.clear()
                    for k, v in data.items():
                        self.upload_tasks[k] = v
        except Exception as e:
            print(f"작업 파일 로드 실패: {e}")

    async def create_upload_task(self, task_id: str, filename: str):
        """새 업로드 태스크 생성"""
        async with self.upload_tasks_lock:
            self.upload_tasks[task_id] = {
                "status": "uploaded",
                "message": "파일 업로드 완료, 큐에 등록됨",
                "filename": filename,
                "created_at": self._now_iso(),
                "updated_at": self._now_iso(),
                "progress": 0,
            }

    async def process_uploaded_file(self, task_id: str, filename: str, rag_service):
        """백그라운드에서 문서 분석을 수행하고 상태를 갱신합니다."""
        async with self.upload_tasks_lock:
            self.upload_tasks[task_id] = {
                "status": "processing",
                "message": "처리 시작",
                "filename": filename,
                "created_at": self._now_iso(),
                "updated_at": self._now_iso(),
                "progress": 0,
            }
        await self.save_tasks_to_file()

        # 메인 스레드의 이벤트 루프 캡처 (스레드에서 콜백 시 사용)
        loop = asyncio.get_running_loop()

        def progress_cb(pct: int, msg: str):
            # 비동기 함수 내에서 동기 콜백이 호출되므로, 
            # 이벤트 루프에 안전하게 작업을 예약해야 함
            async def _update():
                async with self.upload_tasks_lock:
                    if task_id in self.upload_tasks:
                        t = self.upload_tasks[task_id]
                        # 진행률이 뒤로 가는 것을 방지
                        current_prog = t.get("progress", 0)
                        new_prog = max(0, min(100, int(pct)))
                        if new_prog >= current_prog:
                            t["progress"] = new_prog
                            t["message"] = msg
                            t["updated_at"] = self._now_iso()
                            self.upload_tasks[task_id] = t
                await self.save_tasks_to_file()
                
            # 스레드 안전하게 메인 루프에 코루틴 예약
            asyncio.run_coroutine_threadsafe(_update(), loop)

        try:
            # target_filename 인자를 전달하여 해당 파일만 즉시 처리하도록 최적화
            result = await asyncio.to_thread(
                rag_service.ingest_documents, 
                target_filename=filename, 
                progress_callback=progress_cb
            )
            
            async with self.upload_tasks_lock:
                if task_id in self.upload_tasks:
                    self.upload_tasks[task_id]["status"] = "done"
                    self.upload_tasks[task_id]["message"] = str(result)
                    self.upload_tasks[task_id]["progress"] = 100
                    self.upload_tasks[task_id]["updated_at"] = self._now_iso()
            await self.save_tasks_to_file()
            
        except Exception as e:
            async with self.upload_tasks_lock:
                if task_id in self.upload_tasks:
                    self.upload_tasks[task_id]["status"] = "failed"
                    self.upload_tasks[task_id]["message"] = str(e)
                    self.upload_tasks[task_id]["updated_at"] = self._now_iso()
            await self.save_tasks_to_file()
            print(f"처리 중 에러 발생: {e}")
            traceback.print_exc()

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """태스크 상태 조회"""
        async with self.upload_tasks_lock:
            return self.upload_tasks.get(task_id)

    async def list_all_tasks(self) -> Dict[str, Dict[str, Any]]:
        """모든 태스크 목록 반환"""
        async with self.upload_tasks_lock:
            return {k: v for k, v in self.upload_tasks.items()}

    async def cleanup_old_tasks(self):
        """오래된 태스크를 정리하고 주기적으로 파일에 저장"""
        while True:
            try:
                cutoff = datetime.utcnow() - timedelta(days=settings.TASK_RETENTION_DAYS)
                cutoff_iso = cutoff.isoformat() + "Z"
                removed = []
                async with self.upload_tasks_lock:
                    for k, v in list(self.upload_tasks.items()):
                        created = v.get("created_at")
                        if created and created < cutoff_iso:
                            removed.append(k)
                            del self.upload_tasks[k]
                if removed:
                    await self.save_tasks_to_file()
                    print(f"정리된 태스크: {removed}")
            except Exception as e:
                print(f"정리 작업 중 오류: {e}")
            await asyncio.sleep(60 * 60)  # 1시간 간격


# 전역 서비스 인스턴스
upload_service = UploadService()