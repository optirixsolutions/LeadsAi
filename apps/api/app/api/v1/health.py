"""Liveness and readiness probes.

`live` only proves the process is serving. `ready` checks each dependency and reports
per-dependency status; it returns 503 if any required dependency is unavailable.
"""

import logging
import time
from collections.abc import Callable
from typing import Literal

import redis
from fastapi import APIRouter, Response
from pydantic import BaseModel

from app import __version__
from app.core.config import get_settings
from app.core.db import check_database

router = APIRouter(prefix="/health", tags=["health"])
log = logging.getLogger(__name__)


class DependencyStatus(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: float | None = None
    error: str | None = None


class LiveResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadyResponse(BaseModel):
    status: Literal["ok", "degraded"]
    dependencies: dict[str, DependencyStatus]


def _probe(name: str, fn: Callable[[], object]) -> DependencyStatus:
    start = time.perf_counter()
    try:
        fn()
    except Exception as exc:
        # Log the type only; driver messages can include hostnames or credentials.
        log.warning(
            "dependency_unavailable", extra={"dependency": name, "error_type": type(exc).__name__}
        )
        return DependencyStatus(status="error", error=type(exc).__name__)
    return DependencyStatus(status="ok", latency_ms=round((time.perf_counter() - start) * 1000, 2))


def _check_redis() -> None:
    client = redis.Redis.from_url(
        get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2
    )
    try:
        client.ping()
    finally:
        client.close()


@router.get("/live", response_model=LiveResponse)
def live() -> LiveResponse:
    return LiveResponse(status="ok", service=get_settings().service_name, version=__version__)


@router.get("/ready", response_model=ReadyResponse)
def ready(response: Response) -> ReadyResponse:
    deps = {"database": _probe("database", check_database), "redis": _probe("redis", _check_redis)}
    ok = all(d.status == "ok" for d in deps.values())
    if not ok:
        response.status_code = 503
    return ReadyResponse(status="ok" if ok else "degraded", dependencies=deps)
