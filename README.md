# AI Tool

面向单台 Ubuntu 主机的轻量运维控制台，用统一项目视图管理 systemd、用户级 systemd、Docker Compose、端口检查和定时任务。

## 功能

- 主机 CPU、负载、内存、磁盘和运行时间概览
- 按项目聚合 systemd、用户级 systemd 和 Docker Compose 组件
- TCP 与 HTTP 健康检查
- 经过双重白名单校验的启动、停止和重启操作
- systemd journal、Docker Compose 和定时任务日志
- 登录会话、CSRF 防护、登录限流和完整操作审计
- 响应式 Web 控制台

## 本地开发

需要 Python 3.10+ 和 Node.js 20+。

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
npm --prefix frontend install
npm --prefix frontend run build
$env:AI_TOOL_DEMO = "1"
$env:AI_TOOL_PASSWORD = "dev-password"
.\.venv\Scripts\uvicorn app.main:app --app-dir backend --reload --port 8000
```

访问 `http://127.0.0.1:8000`，本地演示模式用户名为 `admin`。

## 测试

```powershell
.\.venv\Scripts\pytest
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

## 生产部署

仓库内的 `deploy/install.sh` 面向 Ubuntu 24.04，会将应用安装到 `/data/ai-tool`，创建独立的 `ai-tool` 系统账户，并安装 root 拥有的动作白名单辅助程序。部署参数和具体步骤见 [deploy/README.md](deploy/README.md)。
