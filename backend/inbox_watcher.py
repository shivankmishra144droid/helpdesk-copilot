"""Watch knowledge/{seller|buyer}/inbox/ and ingest new files while the server runs."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from ingest import INBOX_DIRNAME, scan_inbox
from kb_manager import VALID_CALLER_TYPES, kb_path

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 1.5


class InboxWatcher:
    def __init__(
        self,
        on_ingested: Callable[[str, dict], None] | None = None,
    ):
        self._on_ingested = on_ingested
        self._observer: Observer | None = None
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _caller_type_for_path(self, path: Path) -> str | None:
        parts = [p.lower() for p in path.parts]
        for caller_type in VALID_CALLER_TYPES:
            if caller_type in parts and INBOX_DIRNAME in parts:
                return caller_type
        return None

    def _schedule_scan(self, caller_type: str) -> None:
        with self._lock:
            existing = self._timers.get(caller_type)
            if existing:
                existing.cancel()

            timer = threading.Timer(
                DEBOUNCE_SECONDS,
                self._run_scan,
                args=(caller_type,),
            )
            timer.daemon = True
            self._timers[caller_type] = timer
            timer.start()

    def _run_scan(self, caller_type: str) -> None:
        with self._lock:
            self._timers.pop(caller_type, None)

        try:
            summary = scan_inbox(kb_path(caller_type))
            ingested = summary.get("files_ingested", [])
            if ingested:
                logger.info(
                    "Inbox ingest [%s]: %s file(s) -> %s branch(es) total",
                    caller_type,
                    len(ingested),
                    summary.get("total_branches"),
                )
                for item in ingested:
                    logger.info("  + %s", item.get("file"))
            if summary.get("files_failed"):
                for fail in summary["files_failed"]:
                    logger.error(
                        "Inbox ingest failed [%s] %s: %s",
                        caller_type,
                        fail.get("file"),
                        fail.get("error"),
                    )
            if self._on_ingested and ingested:
                self._on_ingested(caller_type, summary)
        except Exception:
            logger.exception("Inbox scan failed for %s", caller_type)

    def _handle_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return

        path = Path(event.src_path)
        if event.event_type == "moved" and getattr(event, "dest_path", None):
            path = Path(event.dest_path)

        caller_type = self._caller_type_for_path(path)
        if not caller_type:
            return

        self._schedule_scan(caller_type)

    def start(self) -> None:
        handler = _InboxEventHandler(self._handle_event)
        self._observer = Observer()
        for caller_type in VALID_CALLER_TYPES:
            inbox = kb_path(caller_type).parent / INBOX_DIRNAME
            inbox.mkdir(parents=True, exist_ok=True)
            self._observer.schedule(handler, str(inbox), recursive=False)
            logger.info("Watching inbox: %s", inbox)

        self._observer.daemon = True
        self._observer.start()

    def stop(self) -> None:
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None


class _InboxEventHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[FileSystemEvent], None]):
        self._callback = callback

    def on_created(self, event: FileSystemEvent) -> None:
        self._callback(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._callback(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._callback(event)
