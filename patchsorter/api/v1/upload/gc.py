"""Garbage collector for expired UploadSessionActor instances.

Implemented as a plain daemon thread (not a Ray actor) that periodically
queries Ray's own actor-state API, checks how long each ``UploadSessionActor``
has been running, and terminates actors that exceed the configured TTL.

No registry or registration calls are needed — Ray already tracks all live actors.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Imported at module level so tests can patch them.
# ray and ray.util.state are only available when a Ray cluster is running.
try:
    import ray
    from ray.util.state import list_actors
except ImportError:
    ray = None  # type: ignore[assignment]
    list_actors = None  # type: ignore[assignment]


def _cleanup_expired_sessions(ttl_seconds: int) -> None:
    """Shut down any live UploadSessionActors whose age exceeds *ttl_seconds*."""
    if ray is None:
        log.warning("GC: ray not available")
        return

    now_ms = time.time() * 1000
    try:
        actors = list_actors(
            filters=[
                ("class_name", "=", "UploadSessionActor"),
                ("state", "=", "ALIVE"),
            ]
        )
    except Exception as exc:
        log.warning("GC: failed to list actors: %s", exc)
        return

    live_session_ids: set[str] = set()
    for actor in actors:
        name = actor.get("name", "")
        if name and name.startswith("upload_session_"):
            session_id = name[len("upload_session_"):]
            live_session_ids.add(session_id)

    for actor in actors:
        start_ms = actor.get("start_time_ms") or 0
        age_seconds = (now_ms - start_ms) / 1000
        if age_seconds <= ttl_seconds:
            continue

        name = actor.get("name", actor.get("actor_id", "<unknown>"))
        log.info("GC: terminating expired session actor %s (age=%.0fs)", name, age_seconds)
        try:
            handle = ray.get_actor(name) if actor.get("name") else None
        except Exception:
            handle = None

        if handle is not None:
            try:
                ray.get(handle.__ray_terminate__.remote(), timeout=10)
            except Exception as exc:
                log.debug("GC: __ray_terminate__() call failed for %s: %s", name, exc)

    _cleanup_abandoned_temp_dirs(live_session_ids)


def _cleanup_abandoned_temp_dirs(live_session_ids: set[str]) -> None:
    """Remove temp directories left behind by gone UploadSessionActors."""
    prefix = "ps_upload_"
    temp_root = Path(tempfile.gettempdir())

    for entry in temp_root.iterdir():
        if not entry.is_dir():
            continue
        if not entry.name.startswith(prefix):
            continue

        # Parse session_id from "ps_upload_{session_id}_..."
        suffix = entry.name[len(prefix):]
        session_id = suffix.split("_")[0]
        if not session_id:
            continue

        if session_id in live_session_ids:
            continue

        try:
            shutil.rmtree(entry)
            log.info("GC: removed abandoned temp dir %s (session=%s)", entry, session_id)
        except Exception as exc:
            log.debug("GC: failed to remove temp dir %s: %s", entry, exc)


def start_gc_thread(
    ttl_seconds: int = 3600,
    interval_seconds: int = 300,
) -> threading.Thread:
    """Start and return a daemon thread that periodically cleans up expired sessions."""

    def _loop() -> None:
        while True:
            time.sleep(interval_seconds)
            try:
                _cleanup_expired_sessions(ttl_seconds)
            except Exception as exc:
                log.warning("GC: unexpected error during cleanup: %s", exc)

    thread = threading.Thread(target=_loop, daemon=True, name="upload-session-gc")
    thread.start()
    log.info(
        "GC: started (ttl=%ds, interval=%ds)",
        ttl_seconds,
        interval_seconds,
    )
    return thread
