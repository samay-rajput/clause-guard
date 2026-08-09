"""In-process job runner with SSE-consumable progress.

Long pipeline runs (review, autodraft) execute in a worker thread; their
`progress=` callbacks append to the job's message list, which the SSE endpoint
streams. Heavy torch work is serialized through one semaphore — MuRIL inference
under concurrent requests buys nothing on a 1-CPU box and risks thrashing."""
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cg-job")
_heavy = threading.Semaphore(1)
_jobs: dict = {}
_jobs_lock = threading.Lock()

JOB_TTL_S = 3600            # finished jobs stay fetchable for an hour
RESULT_STATES = ("done", "error")


def _reap() -> None:
    now = time.monotonic()
    with _jobs_lock:
        dead = [k for k, j in _jobs.items()
                if j["status"] in RESULT_STATES and now - j["finished"] > JOB_TTL_S]
        for k in dead:
            del _jobs[k]


def submit(fn, *, owner: str, kind: str) -> str:
    """Run fn(progress_cb) in a worker thread; returns the job id."""
    _reap()
    job_id = uuid.uuid4().hex[:16]
    job = {"id": job_id, "kind": kind, "owner": owner, "status": "queued",
           "messages": [], "result": None, "error": None,
           "created": time.monotonic(), "finished": None}
    with _jobs_lock:
        _jobs[job_id] = job

    def progress(msg: str) -> None:
        job["messages"].append(str(msg))

    def run() -> None:
        with _heavy:
            job["status"] = "running"
            try:
                job["result"] = fn(progress)
                job["status"] = "done"
            except Exception as e:                        # surfaced, never lost
                job["error"] = f"{type(e).__name__}: {e}"
                job["status"] = "error"
            finally:
                job["finished"] = time.monotonic()

    _executor.submit(run)
    return job_id


def get(job_id: str, owner: str = None):
    job = _jobs.get(job_id)
    if job and owner is not None and job["owner"] != owner:
        return None                                       # jobs are private
    return job


async def sse_events(job_id: str, owner: str):
    """Async generator for sse-starlette: named progress events while the job
    runs, then one result/error event. Polls the message list — the worker is
    a plain thread, so no cross-thread asyncio plumbing to get wrong."""
    import asyncio
    import json

    sent = 0
    while True:
        job = get(job_id, owner)
        if job is None:
            yield {"event": "error", "data": json.dumps({"error": "unknown job"})}
            return
        while sent < len(job["messages"]):
            yield {"event": "progress",
                   "data": json.dumps({"step": sent + 1,
                                       "message": job["messages"][sent]},
                                      ensure_ascii=False)}
            sent += 1
        if job["status"] in RESULT_STATES:
            if job["status"] == "done":
                yield {"event": "result",
                       "data": json.dumps(job["result"], ensure_ascii=False,
                                          default=str)}
            else:
                yield {"event": "error",
                       "data": json.dumps({"error": job["error"]})}
            return
        await asyncio.sleep(0.25)
