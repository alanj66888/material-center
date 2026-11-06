"""A single background scan; failures leave the published index unchanged."""
import threading
import time
import uuid


class ScanJobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.current = {"running": False}
        self.history = {}

    def status(self, identifier=None):
        with self.lock:
            return dict(
                self.current
                if not identifier or identifier == self.current.get("id")
                else self.history.get(
                    identifier,
                    {"error": "扫描任务记录已过期", "running": False, "phase": "failed"},
                )
            )

    def start(self, path, scan):
        with self.lock:
            if self.current.get("running"):
                raise ValueError("已有扫描任务正在运行，请等待完成")
            identifier = uuid.uuid4().hex
            self.current = {
                "id": identifier,
                "running": True,
                "phase": "walking",
                "path": path,
                "files": 0,
                "directories": 0,
                "started": time.time(),
                "error": "",
            }

        def report(**values):
            with self.lock:
                self.current.update(values)
                if not self.current["running"]:
                    self.history[identifier] = dict(self.current)
                    while len(self.history) > 16:
                        self.history.pop(next(iter(self.history)))

        def run():
            try:
                count = scan(path, progress=report)
                report(running=False, phase="done", count=count, finished=time.time())
            except Exception as error:
                report(
                    running=False,
                    phase="failed",
                    error=str(error),
                    finished=time.time(),
                )

        threading.Thread(target=run, name="catalog-scan", daemon=True).start()
        return self.status()


SCANS = ScanJobs()
