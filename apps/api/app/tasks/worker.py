"""Workflow worker process: `python -m app.tasks.worker`.

Deployed separately from the API. Any number can run: claims are atomic, and a run from a worker
that died is picked up by another once its lease expires.
"""

import logging
import signal
import socket
import threading
import uuid
from types import FrameType

import redis

from app.core.config import get_settings, validate_worker_runtime
from app.observability.logging import configure_logging
from app.workflows.runner import run_once, sweep_checkpoints
from app.workflows.state import HEARTBEAT_KEY

log = logging.getLogger(__name__)

HEARTBEAT_TTL_S = 30
SWEEP_INTERVAL_S = 3600


def _publish_heartbeat(stop: threading.Event) -> None:
    """Lets the status page tell people whether anything is working the queue."""
    client = redis.Redis.from_url(
        get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
    )
    while not stop.is_set():
        try:
            client.set(HEARTBEAT_KEY, "1", ex=HEARTBEAT_TTL_S)
        except redis.RedisError as exc:
            log.warning("worker_heartbeat_failed", extra={"error_type": type(exc).__name__})
        stop.wait(HEARTBEAT_TTL_S / 3)


def _sweep(stop: threading.Event) -> None:
    while not stop.wait(SWEEP_INTERVAL_S):
        try:
            sweep_checkpoints()
        except Exception as exc:
            log.warning("checkpoint_sweep_failed", extra={"error_type": type(exc).__name__})


def _work(owner: str, stop: threading.Event) -> None:
    poll = get_settings().worker_poll_seconds
    imports_first = False
    while not stop.is_set():
        imports_first = not imports_first
        try:
            if not run_once(owner, imports_first=imports_first):
                stop.wait(poll)
        except Exception as exc:
            # A database outage must not end the worker; it keeps trying.
            log.exception("worker_loop_error", extra={"error_type": type(exc).__name__})
            stop.wait(poll)


def main() -> None:
    settings = get_settings()
    validate_worker_runtime(settings)
    configure_logging(settings.log_level, f"{settings.service_name}-worker", settings.log_json)
    stop = threading.Event()

    def _stop(_: int, __: FrameType | None) -> None:
        # Finishes the current step's model call at most; an unfinished run is recovered later.
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    threading.Thread(target=_publish_heartbeat, args=(stop,), daemon=True).start()
    threading.Thread(target=_sweep, args=(stop,), daemon=True).start()

    base = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    threads = [
        threading.Thread(target=_work, args=(f"{base}-{i}", stop), daemon=True)
        for i in range(settings.worker_concurrency)
    ]
    for t in threads:
        t.start()
    log.info("worker_started", extra={"concurrency": settings.worker_concurrency})
    while not stop.is_set():
        stop.wait(1)
    for t in threads:
        t.join(timeout=10)


if __name__ == "__main__":
    main()
