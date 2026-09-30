"""FastAPI application exposing the sandbox REST API."""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agent_sandbox import __version__
from agent_sandbox.auth import require_api_key
from agent_sandbox.backends.base import WORKSPACE, ExecOutput
from agent_sandbox.config import Settings
from agent_sandbox.errors import PayloadTooLargeError, SandboxError
from agent_sandbox.manager import CreateOptions, SandboxManager, normalize_path
from agent_sandbox.models import (
    ErrorResponse,
    ExecRequest,
    ExecResponse,
    FileInfo,
    FileList,
    ForkRequest,
    Health,
    RollbackRequest,
    Sandbox,
    SandboxCreate,
    SandboxList,
    Snapshot,
    SnapshotCreate,
    SnapshotList,
    TimeoutUpdate,
)

log = logging.getLogger(__name__)

# Explicit descriptions keep the spec identical across Python versions, whose
# HTTP reason phrases differ (for example, 413 changed in Python 3.13).
_ERROR_DESCRIPTIONS = {
    400: "Invalid request",
    401: "Missing or invalid API key",
    403: "Forbidden by server policy",
    404: "Not found",
    409: "Conflict",
    413: "Payload too large",
    429: "Sandbox limit reached",
    502: "Backend error",
}
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": text} for code, text in _ERROR_DESCRIPTIONS.items()
}

_HTTP_CODES = {401: "unauthorized", 404: "not_found", 405: "method_not_allowed"}

API_DESCRIPTION = """
Disposable, self-hosted sandboxes where AI agents run code, with snapshot,
rollback, and fork.

Authenticate every `/v1` request with `Authorization: Bearer <key>` or
`X-API-Key: <key>`.
"""


def _manager(request: Request) -> SandboxManager:
    manager: SandboxManager = request.app.state.manager
    return manager


def _sandbox(manager: SandboxManager, sandbox_id: str) -> Sandbox:
    record = manager.get(sandbox_id)
    return Sandbox.from_record(record, manager.status(sandbox_id))


def _ndjson_events(manager: SandboxManager, sandbox_id: str, body: ExecRequest) -> Iterator[bytes]:
    started = time.monotonic()
    events = manager.exec_stream(
        sandbox_id,
        body.command,
        env=body.env,
        workdir=body.workdir,
        timeout_seconds=body.timeout_seconds,
    )

    def generate() -> Iterator[bytes]:
        decoders = {
            "stdout": codecs.getincrementaldecoder("utf-8")(errors="replace"),
            "stderr": codecs.getincrementaldecoder("utf-8")(errors="replace"),
        }
        for event in events:
            if isinstance(event, ExecOutput):
                text = decoders[event.stream].decode(event.data)
                if text:
                    yield (json.dumps({"type": event.stream, "data": text}) + "\n").encode()
            else:
                for name, decoder in decoders.items():
                    tail = decoder.decode(b"", final=True)
                    if tail:
                        yield (json.dumps({"type": name, "data": tail}) + "\n").encode()
                payload = {
                    "type": "exit",
                    "exit_code": event.exit_code,
                    "timed_out": event.timed_out,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                }
                yield (json.dumps(payload) + "\n").encode()

    return generate()


def build_router() -> APIRouter:
    router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)], responses=ERROR_RESPONSES)

    @router.post("/sandboxes", status_code=status.HTTP_201_CREATED, tags=["sandboxes"])
    def create_sandbox(body: SandboxCreate, request: Request) -> Sandbox:
        """Create and start a sandbox."""
        manager = _manager(request)
        record = manager.create(
            CreateOptions(
                image=body.image,
                cpus=body.cpus,
                memory_mb=body.memory_mb,
                pids_limit=body.pids_limit,
                network=body.network,
                read_only_rootfs=body.read_only_rootfs,
                timeout_seconds=body.timeout_seconds,
                env=body.env,
            )
        )
        return Sandbox.from_record(record, "running")

    @router.get("/sandboxes", tags=["sandboxes"])
    def list_sandboxes(request: Request) -> SandboxList:
        """List live sandboxes."""
        manager = _manager(request)
        return SandboxList(sandboxes=[Sandbox.from_record(r, manager.status(r.id)) for r in manager.list_sandboxes()])

    @router.get("/sandboxes/{sandbox_id}", tags=["sandboxes"])
    def get_sandbox(sandbox_id: str, request: Request) -> Sandbox:
        """Get one sandbox."""
        return _sandbox(_manager(request), sandbox_id)

    @router.delete("/sandboxes/{sandbox_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["sandboxes"])
    def delete_sandbox(sandbox_id: str, request: Request) -> Response:
        """Destroy a sandbox and its workspace. Snapshots of it remain."""
        _manager(request).destroy(sandbox_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/sandboxes/{sandbox_id}/timeout", tags=["sandboxes"])
    def set_timeout(sandbox_id: str, body: TimeoutUpdate, request: Request) -> Sandbox:
        """Reset the sandbox's time to live, counted from now."""
        manager = _manager(request)
        manager.set_timeout(sandbox_id, body.timeout_seconds)
        return _sandbox(manager, sandbox_id)

    @router.post("/sandboxes/{sandbox_id}/exec", tags=["exec"])
    def exec_command(sandbox_id: str, body: ExecRequest, request: Request) -> ExecResponse:
        """Run a command to completion and return its output."""
        result = _manager(request).exec(
            sandbox_id,
            body.command,
            env=body.env,
            workdir=body.workdir,
            timeout_seconds=body.timeout_seconds,
        )
        return ExecResponse.from_result(result)

    @router.post(
        "/sandboxes/{sandbox_id}/exec/stream",
        tags=["exec"],
        response_class=StreamingResponse,
        responses={
            200: {
                "description": (
                    'Newline-delimited JSON. Each line is `{"type": "stdout"|"stderr", "data": str}` '
                    'and the last line is `{"type": "exit", "exit_code": int, "timed_out": bool, '
                    '"duration_ms": int}`.'
                ),
                "content": {"application/x-ndjson": {"schema": {"type": "string"}}},
            }
        },
    )
    def exec_stream(sandbox_id: str, body: ExecRequest, request: Request) -> StreamingResponse:
        """Run a command and stream its output as it happens."""
        events = _ndjson_events(_manager(request), sandbox_id, body)
        return StreamingResponse(events, media_type="application/x-ndjson")

    @router.get(
        "/sandboxes/{sandbox_id}/files",
        tags=["files"],
        response_class=Response,
        responses={200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}},
    )
    def read_file(
        sandbox_id: str,
        request: Request,
        path: str = Query(description="Absolute path, or a path relative to /workspace."),
    ) -> Response:
        """Download a file."""
        data = _manager(request).read_file(sandbox_id, path)
        return Response(content=data, media_type="application/octet-stream")

    @router.put(
        "/sandboxes/{sandbox_id}/files",
        tags=["files"],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
            }
        },
    )
    async def write_file(
        sandbox_id: str,
        request: Request,
        path: str = Query(description="Destination under /workspace. Parent directories are created."),
        mode: str = Query(default="644", pattern="^[0-7]{3,4}$", description="Octal permission bits."),
    ) -> FileInfo:
        """Upload a file into the workspace."""
        manager = _manager(request)
        limit = manager.settings.max_file_bytes
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            raise PayloadTooLargeError(f"file exceeds {limit} bytes")
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > limit:
                raise PayloadTooLargeError(f"file exceeds {limit} bytes")
        data = bytes(chunks)
        target = await run_in_threadpool(manager.write_file, sandbox_id, path, data, int(mode, 8))
        return FileInfo(
            name=target.rsplit("/", 1)[-1],
            path=target,
            type="file",
            size=len(data),
            modified_at=datetime.now(tz=UTC),
        )

    @router.get("/sandboxes/{sandbox_id}/files/list", tags=["files"])
    def list_files(
        sandbox_id: str,
        request: Request,
        path: str = Query(default=WORKSPACE, description="Directory to list."),
    ) -> FileList:
        """List a directory."""
        manager = _manager(request)
        entries = manager.list_files(sandbox_id, path)
        return FileList(path=normalize_path(path), entries=[FileInfo.from_entry(e) for e in entries])

    @router.post(
        "/sandboxes/{sandbox_id}/snapshots",
        status_code=status.HTTP_201_CREATED,
        tags=["snapshots"],
    )
    def create_snapshot(sandbox_id: str, request: Request, body: SnapshotCreate | None = None) -> Snapshot:
        """Capture the sandbox's /workspace."""
        snap = _manager(request).snapshot(sandbox_id, name=body.name if body else None)
        return Snapshot.from_record(snap)

    @router.post("/sandboxes/{sandbox_id}/rollback", tags=["snapshots"])
    def rollback(sandbox_id: str, body: RollbackRequest, request: Request) -> Sandbox:
        """Restore a snapshot into the sandbox. Running processes stop and /tmp is cleared."""
        manager = _manager(request)
        manager.rollback(sandbox_id, body.snapshot_id)
        return _sandbox(manager, sandbox_id)

    @router.get("/snapshots", tags=["snapshots"])
    def list_snapshots(
        request: Request,
        sandbox_id: str | None = Query(default=None, description="Only return snapshots of this sandbox."),
    ) -> SnapshotList:
        """List snapshots."""
        snaps = _manager(request).list_snapshots(sandbox_id)
        return SnapshotList(snapshots=[Snapshot.from_record(s) for s in snaps])

    @router.get("/snapshots/{snapshot_id}", tags=["snapshots"])
    def get_snapshot(snapshot_id: str, request: Request) -> Snapshot:
        """Get one snapshot."""
        return Snapshot.from_record(_manager(request).get_snapshot(snapshot_id))

    @router.delete("/snapshots/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["snapshots"])
    def delete_snapshot(snapshot_id: str, request: Request) -> Response:
        """Delete a snapshot."""
        _manager(request).delete_snapshot(snapshot_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/snapshots/{snapshot_id}/fork", status_code=status.HTTP_201_CREATED, tags=["snapshots"])
    def fork(snapshot_id: str, request: Request, body: ForkRequest | None = None) -> Sandbox:
        """Create a new sandbox that starts from a snapshot."""
        opts = body or ForkRequest()
        record = _manager(request).fork(
            snapshot_id,
            timeout_seconds=opts.timeout_seconds,
            network=opts.network,
            cpus=opts.cpus,
            memory_mb=opts.memory_mb,
        )
        return Sandbox.from_record(record, "running")

    return router


async def _reaper(manager: SandboxManager, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await run_in_threadpool(manager.reap_expired)
        except Exception:
            log.exception("TTL reaper iteration failed")


def create_app(settings: Settings | None = None, manager: SandboxManager | None = None) -> FastAPI:
    """Build the application. Tests inject a manager with a fake backend."""
    settings = settings or Settings.from_env()
    if manager is None:
        from agent_sandbox.backends.docker import DockerBackend

        backend = DockerBackend(
            user=settings.sandbox_user,
            runtime=settings.docker_runtime,
            network_name=settings.network_name,
            tmp_size_mb=settings.tmp_size_mb,
        )
        manager = SandboxManager(settings, backend)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await run_in_threadpool(manager.start)
        task = asyncio.create_task(_reaper(manager, settings.reap_interval_seconds))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title="agent-sandbox",
        version=__version__,
        description=API_DESCRIPTION,
        license_info={"name": "Apache-2.0", "identifier": "Apache-2.0"},
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.manager = manager

    @app.exception_handler(SandboxError)
    async def sandbox_error_handler(_: Request, exc: SandboxError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": _HTTP_CODES.get(exc.status_code, "http_error"), "message": str(exc.detail)}},
            headers=exc.headers,
        )

    @app.get("/healthz", tags=["health"])
    def health() -> Health:
        """Report whether the server can reach its backend. No authentication required."""
        manager.backend.ping()
        return Health(status="ok", backend=manager.backend.name, version=__version__)

    app.include_router(build_router())
    return app
