# AI Tool

面向单台 Ubuntu 主机的综合管理控制台，用统一 Web 界面管理软件、开机启动、系统资源、维护任务、Nginx 入口和已部署项目。

## 功能

- 主机 CPU、负载、内存、磁盘和运行时间概览
- CPU、内存、磁盘、inode、块设备、进程、容器、网络与温度详情
- 磁盘 SMART 健康、分区挂载/卸载（限 /mnt、/media）、交换空间与白名单根目录的可下钻目录占用分析
- Samba 目录共享托管：白名单路径、读写/访客控制、testparm 校验与失败回滚；现有 smb.conf / registry 共享自动发现（只读）
- APT/Snap 软件查询、安装、升级和带预览的卸载
- systemd、用户级 systemd 与 Docker 重启策略管理
- 分风险垃圾扫描、固定白名单清理与可回滚系统优化
- 自动发现 Nginx、Docker、systemd 与本机进程提供的 Web 服务
- 托管 Nginx 反向代理入口及访问/错误日志，外部配置保持只读
- 以隔离的 `ai-tool-shell` 低权限账户运行的单会话浏览器终端
- 按项目聚合 systemd、用户级 systemd 和 Docker Compose 组件
- TCP 与 HTTP 健康检查
- 经过双重白名单校验的启动、停止和重启操作
- systemd journal、Docker Compose 和定时任务日志
- 登录会话、CSRF 防护、登录限流和完整操作审计
- 响应式 Web 控制台

`/data` 和 Docker 数据卷不在自动清理或卸载范围内。所有修改系统状态的操作均需要登录、同源与 CSRF 校验，并写入审计记录。

## 本地开发

需要 Python 3.10+ 和 Node.js 20+。

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
npm --prefix frontend install
npm --prefix frontend run build
$env:AI_TOOL_DEMO = "1"
$env:AI_TOOL_PASSWORD = "dev-password"
$env:AI_TOOL_TERMINAL_ENABLED = "0"
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

仓库内的 `deploy/install.sh` 面向 Ubuntu 24.04，会将应用安装到 `/data/ai-tool`，创建独立的 `ai-tool` 系统账户，并安装 root 拥有且严格校验参数的动作辅助程序。部署参数和具体步骤见 [deploy/README.md](deploy/README.md)。
