import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.common.logging import request_id_var, user_id_var


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request_id_var.set(request_id)

        if hasattr(request.state, "user_id"):
            user_id_var.set(request.state.user_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response