"""Bounded, coalesced preview work; obsolete off-screen jobs are discarded."""
from concurrent.futures import Future
from queue import PriorityQueue, Full
import itertools
import threading
import time


class PreviewBusy(RuntimeError):
    pass


class PreviewJobs:
    def __init__(self, workers=2, pending=24):
        self.queue = PriorityQueue(maxsize=pending)
        self.lock = threading.Lock()
        self.jobs = {}
        self.clients = {}
        self.counter = itertools.count()
        for number in range(workers):
            threading.Thread(
                target=self.worker, name=f"preview-worker-{number}", daemon=True
            ).start()

    def focus(self, client, ids):
        with self.lock:
            self.clients[client] = (set(ids), time.monotonic())
            while len(self.clients) > 64:
                self.clients.pop(next(iter(self.clients)))

    def wanted(self, client, file_id):
        with self.lock:
            focus = self.clients.get(client)
            return focus is None or file_id in focus[0]

    def interested(self, job):
        for client, interactive in job["owners"]:
            if not client or interactive:
                return True
            focus = self.clients.get(client)
            if focus is None or job["file_id"] in focus[0]:
                return True
        return False

    def submit(self, key, file_id, task, client=None, interactive=False, priority=2):
        with self.lock:
            if key in self.jobs:
                job = self.jobs[key]
                job["owners"].add((client, interactive))
                return job["future"]
            future = Future()
            job = {
                "future": future,
                "task": task,
                "owners": {(client, interactive)},
                "file_id": file_id,
            }
            self.jobs[key] = job
            try:
                self.queue.put_nowait((priority, next(self.counter), key, job))
            except Full:
                self.jobs.pop(key, None)
                raise PreviewBusy("预览队列繁忙，稍后自动重试")
            return future

    def worker(self):
        while True:
            _, _, key, job = self.queue.get()
            try:
                with self.lock:
                    wanted = self.interested(job)
                if not wanted:
                    raise PreviewBusy("已取消离开可见区域的预览")
                try:
                    job["future"].set_result(job["task"]())
                except Exception as error:
                    job["future"].set_exception(error)
            except Exception as error:
                job["future"].set_exception(error)
            finally:
                with self.lock:
                    self.jobs.pop(key, None)
                self.queue.task_done()


PREVIEWS = PreviewJobs()
