# 生产部署

AI Tool 固定部署到 `/data/ai-tool`，运行数据写入 `/data/ai-tool-data`，服务器清单与密码哈希位于 `/etc/ai-tool`。

## 首次安装

```bash
git clone https://github.com/clone668/ai_tool.git /data/ai-tool
cd /data/ai-tool
sudo AI_TOOL_ADMIN_PASSWORD='使用独立的强密码' ./deploy/install.sh
```

安装脚本会完成以下工作：

- 创建无登录 shell 的 `ai-tool` 服务账户和隔离的 `ai-tool-shell` 终端账户
- 创建 Python 虚拟环境并构建 React 前端
- 安装 root 拥有的 `/usr/local/libexec/ai-tool-ops` 白名单辅助程序
- 创建 `/data/ai-tool-terminal` 作为隔离的低权限 Web 终端目录
- 安装并启用 `ai-tool.service`
- 在 `0.0.0.0:19090` 提供控制台

## 更新

```bash
cd /data/ai-tool
sudo git pull --ff-only
sudo ./deploy/install.sh
```

不传 `AI_TOOL_ADMIN_PASSWORD` 时会保留现有管理员密码。要修改密码，重新传入新密码运行安装脚本。

## 维护命令

```bash
systemctl status ai-tool
journalctl -u ai-tool -f
sudo -u ai-tool sudo -n /usr/local/libexec/ai-tool-ops snapshot
```

控制台使用 HTTP，适合当前受信任局域网。如果未来通过公网访问，应在前面增加 HTTPS 反向代理，并将 `AI_TOOL_COOKIE_SECURE` 改为 `1`。

## 权限边界

- Web 服务以 `ai-tool` 运行，浏览器终端以不能调用 root helper 的 `ai-tool-shell` 运行。
- 终端使用 controlling PTY 提供 job control；会话断开或登录过期时会回收整个终端进程组。
- APT、systemd、Docker、Nginx 与清理动作只能通过 root 拥有的 helper 执行，参数由 helper 再次校验。
- `/data` 与 Docker volumes 不会被自动清理；Docker 清理仅涉及构建缓存和悬空镜像。
- 可通过 `/etc/ai-tool/ai-tool.env` 中的 `AI_TOOL_TERMINAL_ENABLED=0` 完全关闭 Web 终端。
