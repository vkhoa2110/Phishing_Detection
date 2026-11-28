"""Short-lived extension jobs, independent of the requesting browser window.

Results live in RAM only. The existing analysis service still enforces consent,
provider budgets, concurrency, quotas and optional account history.
"""
import asyncio
from dataclasses import dataclass
import hashlib
import json
import uuid

from fastapi import HTTPException

from app.services.workspace import WorkspaceError


@dataclass
class Job:
    owner: str
    key: str
    digest: str
    identity: str
    task: asyncio.Task | None = None
    result: dict | None = None
    error: dict | None = None
    expiry: asyncio.TimerHandle | None = None
    progress: dict | None = None
    cancel_requested: bool = False
    queued: bool = True


class AnalysisJobs:
    def __init__(self, ttl=900, capacity=64, pending_per_owner=3):
        self.ttl, self.capacity = ttl, capacity
        self.pending_per_owner = pending_per_owner
        self.jobs = {}
        self.owner_locks = {}
        self.closed = False

    def start(self, owner, key, payload, action, *, tracked=False):
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        for job in self.jobs.values():
            if (job.owner, job.key) == (owner, key):
                if job.digest != digest:
                    raise HTTPException(409, "Lượt kiểm tra đã gắn với nội dung khác.")
                return self.view(job)
        if self.closed or len(self.jobs) >= self.capacity:
            raise HTTPException(429, "Đang có nhiều kết quả chờ. Hãy thử lại sau.")
        pending = sum(value.owner == owner and value.result is None and value.error is None for value in self.jobs.values())
        if pending >= self.pending_per_owner:
            raise HTTPException(429, "Bạn đã có ba lượt đang chạy hoặc chờ. Hãy hoàn tất hoặc hủy lượt chờ trước.")
        job = Job(owner, key, digest, str(uuid.uuid4()))
        if tracked:
            job.progress = {"completed": 0, "total": 0, "stage": "queued"}
        self.jobs[job.identity] = job
        job.task = asyncio.create_task(self._run(job, action, tracked))
        return self.view(job)

    async def _run(self, job, action, tracked=False):
        try:
            lock = self.owner_locks.setdefault(job.owner, asyncio.Lock())
            async with lock:
                job.queued = False
                if job.cancel_requested:
                    job.error = {"status": 499, "message": "Đã hủy lượt đang chờ; nội dung chưa được gửi AI."}
                else:
                    job.result = await action(job) if tracked else await action()
        except (HTTPException, WorkspaceError) as exc:
            job.error = {"status": getattr(exc, "status_code", getattr(exc, "status", 500)),
                         "message": str(exc.detail if isinstance(exc, HTTPException) else exc.message)}
        except asyncio.CancelledError:
            raise
        except Exception:
            job.error = {"status": 500, "message": "Chưa hoàn tất lượt kiểm tra. Hãy thử lại khi ứng dụng sẵn sàng."}
        finally:
            # A timer removes sensitive results even if no browser polls again.
            if not self.closed and not job.expiry:
                job.expiry = asyncio.get_running_loop().call_later(self.ttl, self.jobs.pop, job.identity, None)
            lock = self.owner_locks.get(job.owner)
            others = any(value is not job and value.owner == job.owner and value.task and not value.task.done() for value in self.jobs.values())
            if lock and not lock.locked() and not others:
                self.owner_locks.pop(job.owner, None)

    def get(self, owner, identity):
        return self.view(self.find(owner, identity))

    def find(self, owner, identity):
        job = self.jobs.get(identity)
        if not job or job.owner != owner:
            # Recover a start whose HTTP reply was lost, without resubmitting AI.
            job = next((value for value in self.jobs.values() if value.owner == owner and value.key == identity), None)
        if not job or job.owner != owner:
            raise HTTPException(404, "Kết quả đã hết hạn hoặc không thuộc phiên này. Hãy kiểm tra lại.")
        return job

    def cancel(self, owner, identity):
        job = self.find(owner, identity)
        if job.progress is None:
            raise HTTPException(422, "Lượt này không hỗ trợ dừng theo phần.")
        job.cancel_requested = True
        return self.view(job)

    def cancel_waiting(self, owner, identity):
        job = self.find(owner, identity)
        if not job.queued or job.result is not None or job.error is not None:
            raise HTTPException(409, "Lượt này đã bắt đầu hoặc đã hoàn tất. Chỉ hủy được lượt đang chờ.")
        job.cancel_requested = True
        job.queued = False
        job.error = {"status": 499, "message": "Đã hủy lượt đang chờ; nội dung chưa được gửi AI."}
        if job.task:
            job.task.cancel()
        # A task canceled before its first step does not execute its finally.
        if not job.expiry and not self.closed:
            job.expiry = asyncio.get_running_loop().call_later(self.ttl, self.jobs.pop, job.identity, None)
        return self.view(job)

    @staticmethod
    def view(job):
        data = {"id": job.identity, "status": "complete" if job.result is not None else "error" if job.error else "running",
                "queued": job.queued and job.result is None and job.error is None}
        if job.result is not None:
            data["result"] = job.result
        if job.error:
            data["error"] = job.error
        if job.progress is not None:
            data["progress"] = {**job.progress, "cancel_requested": job.cancel_requested}
        return data

    async def close(self):
        self.closed = True
        tasks = [job.task for job in self.jobs.values() if job.task]
        for job in self.jobs.values():
            if job.expiry:
                job.expiry.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.jobs.clear()
        self.owner_locks.clear()
