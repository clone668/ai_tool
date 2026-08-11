import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .database import Database
from .ops import OpsClient, OpsError
from .security import LoginLimiter, verify_password

SESSION_COOKIE = "ai_tool_session"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ActionRequest(BaseModel):
    component_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    action: str = Field(pattern=r"^(start|restart|stop)$")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    origin_parts = urlsplit(origin)
    if origin_parts.netloc != request.headers.get("host"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "请求来源无效")


def _security_headers(response: Response) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'"
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    database = Database(app_settings.data_dir / "ai-tool.db")
    ops = OpsClient(app_settings)
    limiter = LoginLimiter.create()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database.initialize()
        yield

    app = FastAPI(
        title="AI Tool",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.database = database
    app.state.ops = ops
    app.state.login_limiter = limiter

    @app.middleware("http")
    async def security_middleware(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        _security_headers(response)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def require_session(request: Request) -> dict[str, Any]:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已失效")
        session = database.get_session(token)
        if not session:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已失效")
        return session

    def require_csrf(
        request: Request,
        session: Annotated[dict[str, Any], Depends(require_session)],
    ) -> dict[str, Any]:
        _same_origin(request)
        provided = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(provided, session["csrf_token"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "安全令牌无效")
        return session

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        configured = bool(app_settings.password_hash or app_settings.demo_password)
        return {"ok": True, "configured": configured, "demo": app_settings.demo}

    @app.post("/api/auth/login")
    def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
        _same_origin(request)
        ip_address = _client_ip(request)
        if not limiter.allowed(ip_address):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "登录尝试过多，请稍后再试")

        configured_hash = app_settings.password_hash
        valid_password = False
        if configured_hash:
            valid_password = verify_password(payload.password, configured_hash)
        elif app_settings.demo and app_settings.demo_password:
            valid_password = hmac.compare_digest(payload.password, app_settings.demo_password)
        else:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "管理员密码尚未配置")

        if payload.username != "admin" or not valid_password:
            limiter.record_failure(ip_address)
            database.record_audit(
                username=payload.username[:64] or "unknown",
                ip_address=ip_address,
                action="login",
                outcome="denied",
                detail="用户名或密码错误",
            )
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")

        limiter.clear(ip_address)
        session = database.create_session(
            username="admin",
            ip_address=ip_address,
            user_agent=request.headers.get("user-agent", ""),
            hours=app_settings.session_hours,
        )
        response.set_cookie(
            SESSION_COOKIE,
            session.token,
            max_age=app_settings.session_hours * 3600,
            httponly=True,
            secure=app_settings.cookie_secure,
            samesite="strict",
            path="/",
        )
        database.record_audit(
            username="admin",
            ip_address=ip_address,
            action="login",
            outcome="success",
            detail="登录成功",
        )
        return {
            "username": session.username,
            "csrf_token": session.csrf_token,
            "expires_at": session.expires_at,
        }

    @app.get("/api/auth/session")
    def session_info(
        session: Annotated[dict[str, Any], Depends(require_session)],
    ) -> dict[str, Any]:
        return {
            "username": session["username"],
            "csrf_token": session["csrf_token"],
            "expires_at": session["expires_at"],
        }

    @app.post("/api/auth/logout")
    def logout(
        request: Request,
        response: Response,
        session: Annotated[dict[str, Any], Depends(require_csrf)],
    ) -> dict[str, bool]:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            database.delete_session(token)
        response.delete_cookie(SESSION_COOKIE, path="/")
        database.record_audit(
            username=session["username"],
            ip_address=_client_ip(request),
            action="logout",
            outcome="success",
            detail="退出登录",
        )
        return {"ok": True}

    @app.get("/api/dashboard")
    def dashboard(
        _: Annotated[dict[str, Any], Depends(require_session)],
        force: bool = Query(default=False),
    ) -> dict[str, Any]:
        try:
            return ops.snapshot(force=force)
        except OpsError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    @app.get("/api/projects/{project_id}/components/{component_id}/logs")
    def component_logs(
        project_id: str,
        component_id: str,
        _: Annotated[dict[str, Any], Depends(require_session)],
        lines: int = Query(default=200, ge=20, le=1000),
    ) -> dict[str, Any]:
        try:
            content = ops.logs(project_id, component_id, lines)
        except (OpsError, KeyError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        return {"content": content, "lines": lines}

    @app.post("/api/projects/{project_id}/actions")
    def project_action(
        project_id: str,
        payload: ActionRequest,
        request: Request,
        session: Annotated[dict[str, Any], Depends(require_csrf)],
    ) -> dict[str, Any]:
        try:
            result = ops.action(project_id, payload.component_id, payload.action)
        except (OpsError, KeyError) as exc:
            database.record_audit(
                username=session["username"],
                ip_address=_client_ip(request),
                project_id=project_id,
                component_id=payload.component_id,
                action=payload.action,
                outcome="failed",
                detail=str(exc),
            )
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        database.record_audit(
            username=session["username"],
            ip_address=_client_ip(request),
            project_id=project_id,
            component_id=payload.component_id,
            action=payload.action,
            outcome="success",
            detail=result.get("message", "操作完成"),
        )
        return result

    @app.get("/api/audit")
    def audit_log(
        _: Annotated[dict[str, Any], Depends(require_session)],
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        return {"items": database.list_audit(limit)}

    assets_path = app_settings.static_dir / "assets"
    if assets_path.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

    index_path = app_settings.static_dir / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str) -> Response:
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        requested = (app_settings.static_dir / full_path).resolve()
        static_root = app_settings.static_dir.resolve()
        if (
            full_path
            and requested.is_file()
            and requested.is_relative_to(static_root)
            and requested.name != "index.html"
        ):
            return FileResponse(requested)
        if index_path.is_file():
            return FileResponse(index_path, headers={"Cache-Control": "no-cache"})
        return JSONResponse(
            {"service": "AI Tool", "message": "frontend build is unavailable"},
            status_code=503,
        )

    return app


app = create_app()
