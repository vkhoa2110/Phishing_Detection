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


class AnalysisJobs:
    def __init__(self, ttl=900, capacity=64):
        self.ttl, self.capacity = ttl, capacity
        self.jobs = {}
        self.closed = False

    def start(self, owner, key, payload, action):
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        for job in self.jobs.values():
            if (job.owner, job.key) == (owner, key):
                if job.digest != digest:
                    raise HTTPException(409, "Lượt kiểm tra đã gắn với nội dung khác.")
                return self.view(job)
        if self.closed or len(self.jobs) >= self.capacity:
            raise HTTPException(429, "Đang có nhiều kết quả chờ. Hãy thử lại sau.")
        job = Job(owner, key, digest, str(uuid.uuid4()))
        self.jobs[job.identity] = job
        job.task = asyncio.create_task(self._run(job, action))
        return self.view(job)

    async def _run(self, job, action):
        try:
            job.result = await action()
        except (HTTPException, WorkspaceError) as exc:
            job.error = {"status": getattr(exc, "status_code", getattr(exc, "status", 500)),
                         "message": str(exc.detail if isinstance(exc, HTTPException) else exc.message)}
        except asyncio.CancelledError:
            raise
        except Exception:
            job.error = {"status": 500, "message": "Chưa hoàn tất lượt kiểm tra. Hãy thử lại khi ứng dụng sẵn sàng."}
        finally:
            # A timer removes sensitive results even if no browser polls again.
            if not self.closed:
                job.expiry = asyncio.get_running_loop().call_later(self.ttl, self.jobs.pop, job.identity, None)

    def get(self, owner, identity):
        job = self.jobs.get(identity)
        if not job or job.owner != owner:
            # Recover a start whose HTTP reply was lost, without resubmitting AI.
            job = next((value for value in self.jobs.values() if value.owner == owner and value.key == identity), None)
        if not job or job.owner != owner:
            raise HTTPException(404, "Kết quả đã hết hạn hoặc không thuộc phiên này. Hãy kiểm tra lại.")
        return self.view(job)

    @staticmethod
    def view(job):
        data = {"id": job.identity, "status": "complete" if job.result is not None else "error" if job.error else "running"}
        if job.result is not None:
            data["result"] = job.result
        if job.error:
            data["error"] = job.error
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
