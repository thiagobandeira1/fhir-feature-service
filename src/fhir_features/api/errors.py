"""RFC 9457 problem+json errors. Detail strings carry issue codes and counts — never
resource content, patient values, or file paths."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from fhir_features.fhir.bundle import BundleValidationError
from fhir_features.logging_setup import get_logger
from fhir_features.store.read import AmbiguousPatientError

log = get_logger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"


def problem_response(
    status: int, title: str, detail: str, *, code: str | None = None
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
    }
    if code is not None:
        body["code"] = code
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_CONTENT_TYPE)


class NotFoundError(LookupError):
    """A requested entity does not exist (message must stay content-free)."""


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BundleValidationError)
    async def _bundle(request: Request, exc: BundleValidationError) -> JSONResponse:
        return problem_response(422, "Bundle validation failed", exc.detail, code=exc.code)

    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return problem_response(404, "Not found", str(exc), code="not_found")

    @app.exception_handler(AmbiguousPatientError)
    async def _ambiguous(request: Request, exc: AmbiguousPatientError) -> JSONResponse:
        return problem_response(
            409,
            "Ambiguous patient id",
            "the patient id exists under multiple sources; pass ?source=",
            code="ambiguous_patient",
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default echoes input values; ours reports locations only.
        locations = ["/".join(str(part) for part in err.get("loc", ())) for err in exc.errors()]
        return problem_response(
            422,
            "Request validation failed",
            f"invalid request parameters: {', '.join(locations)}",
            code="request_invalid",
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", path=request.url.path, exc_info=True)
        return problem_response(
            500, "Internal server error", "unexpected failure", code="internal_error"
        )
