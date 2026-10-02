from __future__ import annotations

import os
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

load_dotenv()
MAX_BODY_BYTES = 10 * 1024 * 1024
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
              "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length"}


@dataclass(frozen=True)
class Settings:
    upstream_base_url: str
    error_rate: float = 0.10
    delay_rate: float = 0.20
    max_delay_seconds: float = 0.20

    def __post_init__(self) -> None:
        parsed = urlsplit(self.upstream_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("UPSTREAM_BASE_URL must be an absolute http(s) URL")
        if not 0 <= self.error_rate <= 1 or not 0 <= self.delay_rate <= 1:
            raise ValueError("fault rates must be between 0 and 1")
        if self.error_rate + self.delay_rate > 1:
            raise ValueError("error and delay rates cannot add up to more than 1")
        if self.max_delay_seconds < 0:
            raise ValueError("maximum delay must be non-negative")


def choose_fault(value: float, error_rate: float, delay_rate: float) -> str:
    """Map one random value to a fault kind, useful for reproducible tests."""
    if value < error_rate:
        return "error"
    if value < error_rate + delay_rate:
        return "delay"
    return "pass"


def _configured_settings() -> Settings:
    return Settings(os.getenv("UPSTREAM_BASE_URL", "http://127.0.0.1:9000"),
                    float(os.getenv("ERROR_RATE", "0.10")),
                    float(os.getenv("DELAY_RATE", "0.20")),
                    float(os.getenv("MAX_DELAY_SECONDS", "0.20")))


def _headers(source) -> dict[str, str]:
    connection_tokens = {part.strip().lower() for part in source.get("connection", "").split(",")}
    return {key: value for key, value in source.items()
            if key.lower() not in HOP_BY_HOP and key.lower() not in connection_tokens}


def _target_url(base: str, path: str, query: str) -> str:
    parts = urlsplit(base)
    joined_path = parts.path.rstrip("/") + "/" + path.lstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, joined_path, query, ""))


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    config = settings or _configured_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.client = httpx.AsyncClient(transport=transport, timeout=15.0, follow_redirects=False)
        try:
            yield
        finally:
            await app.state.client.aclose()

    app = FastAPI(title="Mock Fault-Tolerant Proxy", version="1.0.0", lifespan=lifespan)

    @app.get("/__health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def proxy(request: Request, path: str = "") -> Response:
        fault = choose_fault(random.random(), config.error_rate, config.delay_rate)
        if fault == "error":
            return JSONResponse({"error": "injected upstream failure"}, status_code=500)
        if fault == "delay":
            import asyncio
            await asyncio.sleep(random.uniform(0, config.max_delay_seconds))
        body_chunks: list[bytes] = []
        body_size = 0
        async for chunk in request.stream():
            body_size += len(chunk)
            if body_size > MAX_BODY_BYTES:
                return JSONResponse({"error": "request body exceeds 10 MiB proxy limit"}, status_code=413)
            body_chunks.append(chunk)
        body = b"".join(body_chunks)
        target = _target_url(config.upstream_base_url, path, request.url.query)
        try:
            upstream_request = app.state.client.build_request(request.method, target,
                headers=_headers(request.headers), content=body)
            async with app.state.client.stream(upstream_request.method, upstream_request.url,
                    headers=upstream_request.headers, content=upstream_request.content) as upstream:
                response_headers = _headers(upstream.headers)
                chunks: list[bytes] = []
                size = 0
                async for chunk in upstream.aiter_raw():
                    size += len(chunk)
                    if size > MAX_BODY_BYTES:
                        return JSONResponse({"error": "upstream response exceeds 10 MiB proxy limit"}, status_code=502)
                    chunks.append(chunk)
                return Response(content=b"".join(chunks), status_code=upstream.status_code, headers=response_headers)
        except httpx.RequestError:
            return JSONResponse({"error": "configured upstream is unavailable"}, status_code=502)

    return app


app = create_app()
