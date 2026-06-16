from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def ok(data: object = None) -> dict[str, object]:
    return {"success": True, "data": data if data is not None else {}}


def fail(message: str, details: object | None = None) -> dict[str, object]:
    return {"success": False, "message": message, "details": details if details is not None else {}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            message = str(exc.detail.get("message") or "Request failed")
            return JSONResponse(status_code=exc.status_code, content=fail(message, exc.detail))
        return JSONResponse(status_code=exc.status_code, content=fail(str(exc.detail), {}))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content=fail("Validation error", exc.errors()))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content=fail("Internal server error", {"type": type(exc).__name__}))
