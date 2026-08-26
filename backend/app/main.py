import asyncio
import hmac
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .database import Database
from .ops import OpsClient, OpsError
from .security import LoginLimiter, verify_password
from .terminal import TerminalUnavailable, serve_terminal

SESSION_COOKIE = "ai_tool_session"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ActionRequest(BaseModel):
    component_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    action: str = Field(pattern=r"^(start|restart|stop)$")


class SoftwareRequest(BaseModel):
    manager: Literal["apt", "snap"]
    name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9+.-]{0,127}(?::[a-z0-9-]+)?$|^_$",
    )
    action: Literal["install", "upgrade", "remove", "purge", "refresh"]
    confirmation_token: str | None = Field(
        default=None, min_length=20, max_length=200, pattern=r"^[A-Za-z0-9_-]+$"
    )


class StartupActionRequest(BaseModel):
    scope: Literal["system", "user", "docker"]
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9@_.:-]+$")
    action: Literal["start", "stop", "restart", "enable", "disable", "policy"]
    value: Literal["_", "no", "always", "unless-stopped", "on-failure"] = "_"


class MaintenanceActionRequest(BaseModel):
    action: Literal[
        "apt-cache",
        "journal-14d",
        "tmp-7d",
        "docker-build-cache",
        "docker-dangling-images",
        "apt-autoremove",
    ]
    confirmation_token: str = Field(
        min_length=20, max_length=200, pattern=r"^[A-Za-z0-9_-]+$"
    )


class OptimizationActionRequest(BaseModel):
    action: Literal[
        "enable-fstrim", "disable-fstrim", "limit-journal", "rollback-journal"
    ]
    confirmation_token: str = Field(
        min_length=20, max_length=200, pattern=r"^[A-Za-z0-9_-]+$"
    )


class WebServiceRequest(BaseModel):
    id: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    name: str = Field(min_length=1, max_length=100)
    domain: str = Field(
        min_length=1,
        max_length=253,
        pattern=r"^(?:\*\.)?[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$",
    )
    upstream_host: Literal["127.0.0.1", "localhost"] = "127.0.0.1"
    upstream_port: int = Field(ge=1, le=65535)
    websocket: bool = True
    enabled: bool = True


class WebActionRequest(BaseModel):
    action: Literal["enable", "disable", "delete", "reload"]


def _client_ip(request: Request | WebSocket) -> str:
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
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'"
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    database = Database(app_settings.data_dir / "ai-tool.db")
    ops = OpsClient(app_settings)
    limiter = LoginLimiter.create()
    terminal_active = False

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

    def audited_operation(
        *,
        request: Request,
        session: dict[str, Any],
        action: str,
        detail: str,
        operation: Callable[[], dict[str, Any]],
        project_id: str | None = None,
        component_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            result = operation()
        except (OpsError, KeyError) as exc:
            database.record_audit(
                username=session["username"],
                ip_address=_client_ip(request),
                project_id=project_id,
                component_id=component_id,
                action=action,
                outcome="failed",
                detail=f"{detail}: {exc}",
            )
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        database.record_audit(
            username=session["username"],
            ip_address=_client_ip(request),
            project_id=project_id,
            component_id=component_id,
            action=action,
            outcome="success",
            detail=result.get("message", detail),
        )
        return result

    def require_confirmation(
        *,
        request: Request,
        session: dict[str, Any],
        token: str | None,
        action: str,
        target: str,
    ) -> None:
        if token and database.consume_confirmation(token, action, target):
            return
        database.record_audit(
            username=session["username"],
            ip_address=_client_ip(request),
            action=action,
            outcome="denied",
            detail=f"确认令牌无效或已过期：{target}",
        )
        raise HTTPException(status.HTTP_409_CONFLICT, "操作预览已过期，请重新预览")

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
            "terminal_enabled": app_settings.terminal_enabled,
        }

    @app.get("/api/auth/session")
    def session_info(
        session: Annotated[dict[str, Any], Depends(require_session)],
    ) -> dict[str, Any]:
        return {
            "username": session["username"],
            "csrf_token": session["csrf_token"],
            "expires_at": session["expires_at"],
            "terminal_enabled": app_settings.terminal_enabled,
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
        return audited_operation(
            request=request,
            session=session,
            action=payload.action,
            detail=f"项目组件 {project_id}/{payload.component_id}",
            project_id=project_id,
            component_id=payload.component_id,
            operation=lambda: ops.action(project_id, payload.component_id, payload.action),
        )

    @app.get("/api/software")
    def software_inventory(
        _: Annotated[dict[str, Any], Depends(require_session)],
        query: str = Query(default="", max_length=128),
        limit: int = Query(default=200, ge=20, le=500),
    ) -> dict[str, Any]:
        try:
            return ops.software(query, limit)
        except OpsError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    @app.post("/api/software/plan")
    def plan_software(
        payload: SoftwareRequest,
        _: Annotated[dict[str, Any], Depends(require_csrf)],
    ) -> dict[str, Any]:
        try:
            result = ops.software_plan(payload.manager, payload.name, payload.action)
        except OpsError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        result["confirmation_token"] = database.create_confirmation(
            f"software.{payload.action}", f"{payload.manager}:{payload.name}"
        )
        return result

    @app.post("/api/software/actions")
    def software_action(
        payload: SoftwareRequest,
        request: Request,
        session: Annotated[dict[str, Any], Depends(require_csrf)],
    ) -> dict[str, Any]:
        if payload.action in {"remove", "purge"}:
            require_confirmation(
                request=request,
                session=session,
                token=payload.confirmation_token,
                action=f"software.{payload.action}",
                target=f"{payload.manager}:{payload.name}",
            )
        return audited_operation(
            request=request,
            session=session,
            action=f"software.{payload.action}",
            detail=f"{payload.manager}:{payload.name}",
            operation=lambda: ops.software_action(
                payload.manager, payload.name, payload.action
            ),
        )

    @app.get("/api/startup")
    def startup_inventory(
        _: Annotated[dict[str, Any], Depends(require_session)],
        query: str = Query(default="", max_length=128),
        limit: int = Query(default=500, ge=20, le=1000),
    ) -> dict[str, Any]:
        try:
            return ops.startup(query, limit)
        except OpsError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    @app.post("/api/startup/actions")
    def startup_action(
        payload: StartupActionRequest,
        request: Request,
        session: Annotated[dict[str, Any], Depends(require_csrf)],
    ) -> dict[str, Any]:
        return audited_operation(
            request=request,
            session=session,
            action=f"startup.{payload.action}",
            detail=f"{payload.scope}:{payload.name}",
            operation=lambda: ops.startup_action(
                payload.scope, payload.name, payload.action, payload.value
            ),
        )

    @app.get("/api/system")
    def system_information(
        _: Annotated[dict[str, Any], Depends(require_session)],
        history_limit: int = Query(default=120, ge=1, le=1440),
    ) -> dict[str, Any]:
        try:
            details = ops.system_details()
        except OpsError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        filesystems = details.get("filesystems", [])
        data_disk = next(
            (item for item in filesystems if item.get("mountpoint") == "/data"),
            max(filesystems, key=lambda item: item.get("percent", 0), default={}),
        )
        cpu = details.get("cpu", {})
        memory = details.get("memory", {})
        loads = cpu.get("load_average", [0])
        database.record_system_metrics(
            cpu_percent=float(cpu.get("percent", 0)),
            memory_percent=float(memory.get("percent", 0)),
            load_one=float(loads[0] if loads else 0),
            disk_percent=float(data_disk.get("percent", 0)),
        )
        details["history"] = database.list_system_metrics(history_limit)
        return details

    @app.get("/api/maintenance")
    def maintenance_information(
        _: Annotated[dict[str, Any], Depends(require_session)],
    ) -> dict[str, Any]:
        try:
            cleanup = ops.maintenance_scan()
            optimization = ops.optimization_scan()
        except OpsError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        for item in cleanup.get("candidates", []):
            if item.get("actionable", True):
                action = f"maintenance.{item['id']}"
                item["confirmation_token"] = database.create_confirmation(action, item["id"])
        for item in optimization.get("recommendations", []):
            confirmation_action = None
            if item.get("id") == "enable-fstrim":
                confirmation_action = (
                    "disable-fstrim" if item.get("status") == "applied" else "enable-fstrim"
                )
            elif item.get("id") == "limit-journal":
                confirmation_action = (
                    "rollback-journal"
                    if item.get("status") == "applied"
                    else "limit-journal"
                )
            if confirmation_action:
                action = f"optimization.{confirmation_action}"
                item["confirmation_action"] = confirmation_action
                item["confirmation_token"] = database.create_confirmation(
                    action, confirmation_action
                )
        return {"cleanup": cleanup, "optimization": optimization}

    @app.post("/api/maintenance/actions")
    def maintenance_action(
        payload: MaintenanceActionRequest,
        request: Request,
        session: Annotated[dict[str, Any], Depends(require_csrf)],
    ) -> dict[str, Any]:
        require_confirmation(
            request=request,
            session=session,
            token=payload.confirmation_token,
            action=f"maintenance.{payload.action}",
            target=payload.action,
        )
        return audited_operation(
            request=request,
            session=session,
            action=f"maintenance.{payload.action}",
            detail=f"清理项 {payload.action}",
            operation=lambda: ops.maintenance_action(payload.action),
        )

    @app.post("/api/optimization/actions")
    def optimization_action(
        payload: OptimizationActionRequest,
        request: Request,
        session: Annotated[dict[str, Any], Depends(require_csrf)],
    ) -> dict[str, Any]:
        require_confirmation(
            request=request,
            session=session,
            token=payload.confirmation_token,
            action=f"optimization.{payload.action}",
            target=payload.action,
        )
        return audited_operation(
            request=request,
            session=session,
            action=f"optimization.{payload.action}",
            detail=f"优化项 {payload.action}",
            operation=lambda: ops.optimization_action(payload.action),
        )

    @app.get("/api/web-services")
    def web_services(
        _: Annotated[dict[str, Any], Depends(require_session)],
    ) -> dict[str, Any]:
        try:
            return ops.web_inventory()
        except OpsError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    @app.put("/api/web-services/{service_id}")
    def save_web_service(
        service_id: str,
        payload: WebServiceRequest,
        request: Request,
        session: Annotated[dict[str, Any], Depends(require_csrf)],
    ) -> dict[str, Any]:
        if service_id != payload.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "服务 ID 不一致")
        return audited_operation(
            request=request,
            session=session,
            action="web-service.save",
            detail=f"Web 服务 {service_id}",
            component_id=service_id,
            operation=lambda: ops.web_upsert(payload.model_dump()),
        )

    @app.post("/api/web-services/{service_id}/actions")
    def web_service_action(
        service_id: str,
        payload: WebActionRequest,
        request: Request,
        session: Annotated[dict[str, Any], Depends(require_csrf)],
    ) -> dict[str, Any]:
        return audited_operation(
            request=request,
            session=session,
            action=f"web-service.{payload.action}",
            detail=f"Web 服务 {service_id}",
            component_id=service_id,
            operation=lambda: ops.web_action(service_id, payload.action),
        )

    @app.get("/api/web-services/{service_id}/logs")
    def web_service_logs(
        service_id: str,
        _: Annotated[dict[str, Any], Depends(require_session)],
        stream: Literal["access", "error"] = Query(default="access"),
        lines: int = Query(default=200, ge=20, le=1000),
    ) -> dict[str, Any]:
        try:
            content = ops.web_logs(service_id, stream, lines)
        except OpsError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        return {"content": content, "stream": stream, "lines": lines}

    @app.get("/api/audit")
    def audit_log(
        _: Annotated[dict[str, Any], Depends(require_session)],
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        return {"items": database.list_audit(limit)}

    @app.websocket("/api/terminal/ws")
    async def terminal_socket(websocket: WebSocket) -> None:
        nonlocal terminal_active
        if not app_settings.terminal_enabled:
            await websocket.close(code=1008, reason="Web 终端未启用")
            return
        origin = websocket.headers.get("origin", "")
        host = websocket.headers.get("host", "")
        origin_parts = urlsplit(origin)
        if origin_parts.scheme not in {"http", "https"} or origin_parts.netloc != host:
            await websocket.close(code=1008, reason="请求来源无效")
            return
        token = websocket.cookies.get(SESSION_COOKIE)
        session = database.get_session(token) if token else None
        if not session:
            await websocket.close(code=1008, reason="登录已失效")
            return

        if terminal_active:
            database.record_audit(
                username=session["username"],
                ip_address=_client_ip(websocket),
                action="terminal.connect",
                outcome="denied",
                detail="已有终端会话正在使用",
            )
            await websocket.close(code=1013, reason="已有终端会话正在使用")
            return
        terminal_active = True

        try:
            await websocket.accept()
            database.record_audit(
                username=session["username"],
                ip_address=_client_ip(websocket),
                action="terminal.connect",
                outcome="success",
                detail="低权限终端已连接",
            )
            expires_at = datetime.fromisoformat(session["expires_at"])
            remaining = max(1.0, (expires_at - datetime.now(timezone.utc)).total_seconds())
            terminal_home = app_settings.terminal_home or (
                app_settings.data_dir / "terminal-home"
            )
            await asyncio.wait_for(
                serve_terminal(websocket, terminal_home), timeout=remaining
            )
        except asyncio.TimeoutError:
            with suppress(RuntimeError):
                await websocket.close(code=1008, reason="登录已失效")
        except TerminalUnavailable as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})
            await websocket.close(code=1011)
        finally:
            terminal_active = False
            database.record_audit(
                username=session["username"],
                ip_address=_client_ip(websocket),
                action="terminal.disconnect",
                outcome="success",
                detail="低权限终端已断开",
            )

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
