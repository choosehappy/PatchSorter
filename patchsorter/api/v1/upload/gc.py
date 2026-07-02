"""Garbage collector for expired UploadSessionActor instances.

Implemented as a plain daemon thread (not a Ray actor) that periodically
queries Ray's own actor-state API, checks how long each ``UploadSessionActor``
has been running, and terminates actors that exceed the configured TTL.

No registry or registration calls are needed — Ray already tracks all live actors.
"""
from __future__ import annotations

import logging
import threading
import time

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
    """Kill any live UploadSessionActors whose age exceeds *ttl_seconds*."""
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
                ray.get(handle.cleanup.remote(), timeout=10)
            except Exception as exc:
                log.debug("GC: cleanup() call failed for %s: %s", name, exc)
            try:
                ray.kill(handle, no_restart=True)
            except Exception as exc:
                log.debug("GC: ray.kill() failed for %s: %s", name, exc)


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
