from __future__ import annotations

from fastapi import HTTPException

STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    500: "internal_error",
    503: "service_unavailable",
}


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message


def code_for_status(status_code: int) -> str:
    return STATUS_CODES.get(status_code, "error")


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def not_found(message: str = "Document not found") -> ApiError:
    return ApiError(404, "not_found", message)


def forbidden(message: str = "You do not have permission for this action") -> ApiError:
    return ApiError(403, "forbidden", message)
