import json
import os
import threading
from datetime import datetime, timezone

from app.config import AGENT_TRACE_DIR, AGENT_TRACE_ENABLED


class TraceCollector:
    def __init__(self, directory: str = AGENT_TRACE_DIR, enabled: bool = AGENT_TRACE_ENABLED):
        self.directory = directory
        self.enabled = enabled
        self._lock = threading.Lock()

    def path_for(self, when: datetime | None = None) -> str:
        when = when or datetime.now(timezone.utc)
        return os.path.join(self.directory, f"traces-{when:%Y%m%d}.jsonl")

    def write(self, record: dict) -> str | None:
        if not self.enabled:
            return None
        record = {"recordedAt": datetime.now(timezone.utc).isoformat(), **record}
        path = self.path_for()
        try:
            os.makedirs(self.directory, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False, default=str)
            with self._lock, open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as e:
            print("trace write failed:", e)
            return None
        return path


class MemoryTraceCollector:
    def __init__(self):
        self.records: list[dict] = []

    def write(self, record: dict) -> str | None:
        self.records.append(record)
        return None


class MultiTraceCollector:
    def __init__(self, *collectors):
        self.collectors = [c for c in collectors if c is not None]

    def write(self, record: dict) -> str | None:
        path = None
        for collector in self.collectors:
            path = collector.write(record) or path
        return path


def summarize_tool_log(tool_log: list[dict]) -> dict:
    signatures = [entry.get("signature") for entry in tool_log]
    return {
        "toolSequence": [entry.get("tool") for entry in tool_log],
        "toolsUsed": sorted({entry.get("tool") for entry in tool_log if entry.get("tool")}),
        "failedCalls": sum(1 for entry in tool_log if entry.get("error")),
        "repeatedSignatures": len(signatures) - len(set(signatures)),
        "cachedCalls": sum(1 for entry in tool_log if entry.get("cached")),
        "toolLatencyMs": round(sum(entry.get("latencyMs") or 0 for entry in tool_log), 1),
        "sources": sorted({entry.get("category") for entry in tool_log if entry.get("category")}),
    }
