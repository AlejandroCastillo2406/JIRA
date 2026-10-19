import logging
import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

try:
    import structlog
    _structured_log = structlog.get_logger()
except ImportError:
    _structured_log = None
_plain_log = logging.getLogger("projectflow.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        values = dict(request_id=request_id, method=request.method, route=request.url.path,
                      status_code=response.status_code, duration_ms=duration_ms)
        if _structured_log:
            _structured_log.info("http_request", **values)
        else:
            _plain_log.info("http_request %s", values)
        return response
