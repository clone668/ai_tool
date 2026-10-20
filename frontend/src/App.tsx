import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, LoaderCircle, RefreshCw, ServerCog, X } from 'lucide-react'
import { api, ApiError } from './api'
import { actionLabels, formatDate } from './format'
import type { ActionName, Component, DashboardSnapshot, Project, SessionInfo } from './types'
import { AuditView } from './components/AuditView'
import { LoginView } from './components/LoginView'
import { LogsView } from './components/LogsView'
import { MaintenanceView } from './components/MaintenanceView'
import { Overview } from './components/Overview'
import { Sidebar, type ViewName } from './components/Sidebar'
import { SoftwareView } from './components/SoftwareView'
import { SharesView } from './components/SharesView'
import { StartupView } from './components/StartupView'
import { StorageView } from './components/StorageView'
import { SystemView } from './components/SystemView'
import { UpdateView } from './components/UpdateView'
import { WebServicesView } from './components/WebServicesView'

const TerminalView = lazy(() => import('./components/TerminalView').then(
  (module) => ({ default: module.TerminalView }),
))

interface PendingAction {
  project: Project
  component: Component
  action: ActionName
}

interface LogSelection {
  projectId: string
  componentId: string
}

const viewTitles: Record<ViewName, { title: string; subtitle: string }> = {
  overview: { title: '运行总览', subtitle: '应用、基础服务与定时任务' },
  software: { title: '软件管理', subtitle: 'APT 与 Snap 软件包' },
  startup: { title: '开机启动', subtitle: 'systemd 与 Docker 重启策略' },
  system: { title: '系统监控', subtitle: '资源、磁盘、进程与网络' },
  storage: { title: '存储管理', subtitle: '文件系统、磁盘健康与目录占用' },
  shares: { title: '目录共享', subtitle: 'Samba 共享的创建与托管' },
  maintenance: { title: '系统维护', subtitle: '清理扫描与可回滚优化' },
  web: { title: 'Web 服务', subtitle: '自动发现、Nginx 入口与访问日志' },
  terminal: { title: '命令终端', subtitle: '隔离的低权限会话' },
  logs: { title: '日志中心', subtitle: 'systemd journal 与容器日志' },
  audit: { title: '操作审计', subtitle: '登录与运维动作记录' },
  update: { title: '系统更新', subtitle: '从 Git 仓库拉取并重新部署' },
}

export default function App() {
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null)
  const [booting, setBooting] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [activeView, setActiveView] = useState<ViewName>('overview')
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const [busyTarget, setBusyTarget] = useState<string | null>(null)
  const [logSelection, setLogSelection] = useState<LogSelection | null>(null)
  const [toast, setToast] = useState<{ message: string; tone: 'success' | 'error' } | null>(null)
  const toastTimer = useRef<number | null>(null)

  const showToast = useCallback((message: string, tone: 'success' | 'error') => {
    if (toastTimer.current) window.clearTimeout(toastTimer.current)
    setToast({ message, tone })
    toastTimer.current = window.setTimeout(() => setToast(null), 4500)
  }, [])

  const expireSession = useCallback(() => {
    setSession(null)
    setSnapshot(null)
    setActiveView('overview')
  }, [])

  const handleViewError = useCallback((message: string, unauthorized = false) => {
    if (unauthorized) {
      expireSession()
      return
    }
    showToast(message, 'error')
  }, [expireSession, showToast])

  const loadDashboard = useCallback(async (force = false, quiet = false) => {
    if (!quiet) setRefreshing(true)
    try {
      const data = await api.dashboard(force)
      setSnapshot(data)
      setLoadError('')
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        expireSession()
      } else {
        const message = error instanceof Error ? error.message : '状态读取失败'
        setLoadError(message)
        if (quiet) showToast(message, 'error')
      }
    } finally {
      if (!quiet) setRefreshing(false)
    }
  }, [expireSession, showToast])

  useEffect(() => {
    let active = true
    async function bootstrap() {
      try {
        const current = await api.session()
        if (!active) return
        setSession(current)
        await loadDashboard()
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) {
          setLoadError(error instanceof Error ? error.message : '控制台初始化失败')
        }
      } finally {
        if (active) setBooting(false)
      }
    }
    void bootstrap()
    return () => { active = false }
  }, [loadDashboard])

  useEffect(() => {
    if (!session) return
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void loadDashboard(false, true)
    }, 15_000)
    return () => window.clearInterval(timer)
  }, [loadDashboard, session])

  useEffect(() => () => {
    if (toastTimer.current) window.clearTimeout(toastTimer.current)
  }, [])

  async function login(username: string, password: string) {
    const current = await api.login(username, password)
    setSession(current)
    setBooting(false)
    await loadDashboard(true)
  }

  async function logout() {
    if (!session) return
    try {
      await api.logout(session.csrf_token)
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        showToast(error instanceof Error ? error.message : '退出失败', 'error')
        return
      }
    }
    expireSession()
  }

  function openLogs(project: Project, component: Component) {
    setLogSelection({ projectId: project.id, componentId: component.id })
    setActiveView('logs')
  }

  async function confirmAction() {
    if (!pendingAction || !session) return
    const { project, component, action } = pendingAction
    const target = `${project.id}/${component.id}`
    setBusyTarget(target)
    try {
      const result = await api.action(session.csrf_token, project.id, component.id, action)
      showToast(result.message || `${actionLabels[action]}完成`, 'success')
      setPendingAction(null)
      await loadDashboard(true, true)
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) expireSession()
      else showToast(error instanceof Error ? error.message : '操作失败', 'error')
    } finally {
      setBusyTarget(null)
    }
  }

  if (booting) {
    return (
      <main className="boot-screen">
        <div className="brand-mark brand-mark-large"><ServerCog size={29} /></div>
        <LoaderCircle className="spin" size={20} />
        <span>正在连接节点</span>
      </main>
    )
  }

  if (!session) return <LoginView onLogin={login} />

  const viewHeading = viewTitles[activeView]
  const hostStatus = snapshot && snapshot.summary.offline === 0 ? 'healthy' : 'degraded'

  return (
    <div className="app-shell">
      <Sidebar
        activeView={activeView}
        username={session.username}
        onView={setActiveView}
        onLogout={() => void logout()}
      />
      <div className="app-main">
        <header className="topbar">
          <div className="topbar-title">
            <h1>{viewHeading.title}</h1>
            <span>{viewHeading.subtitle}</span>
          </div>
          <div className="host-indicator">
            <span className={`status-dot ${hostStatus}`} />
            <div>
              <strong>{snapshot?.host.hostname ?? 'huxi-H81M'}</strong>
              <span>{snapshot?.host.address ?? '192.168.2.240'}</span>
            </div>
          </div>
          {snapshot && (
            <div className="update-indicator">
              <span>最近更新</span>
              <strong>{formatDate(snapshot.generated_at)}</strong>
            </div>
          )}
        </header>

        <main className="content-area">
          {activeView === 'software' ? (
            <SoftwareView
              csrfToken={session.csrf_token}
              onError={handleViewError}
              onSuccess={(message) => showToast(message, 'success')}
            />
          ) : activeView === 'startup' ? (
            <StartupView
              csrfToken={session.csrf_token}
              onError={handleViewError}
              onSuccess={(message) => showToast(message, 'success')}
            />
          ) : activeView === 'system' ? (
            <SystemView onError={handleViewError} />
          ) : activeView === 'storage' ? (
            <StorageView
              csrfToken={session.csrf_token}
              onError={handleViewError}
              onSuccess={(message) => showToast(message, 'success')}
            />
          ) : activeView === 'shares' ? (
            <SharesView
              csrfToken={session.csrf_token}
              onError={handleViewError}
              onSuccess={(message) => showToast(message, 'success')}
            />
          ) : activeView === 'maintenance' ? (
            <MaintenanceView
              csrfToken={session.csrf_token}
              onError={handleViewError}
              onSuccess={(message) => showToast(message, 'success')}
            />
          ) : activeView === 'web' ? (
            <WebServicesView
              csrfToken={session.csrf_token}
              onError={handleViewError}
              onSuccess={(message) => showToast(message, 'success')}
            />
          ) : activeView === 'update' ? (
            <UpdateView
              csrfToken={session.csrf_token}
              onError={handleViewError}
              onSuccess={(message) => showToast(message, 'success')}
            />
          ) : activeView === 'terminal' ? (
            <Suspense fallback={<div className="load-failure dashboard-loading"><LoaderCircle className="spin" size={28} /><strong>正在载入终端</strong></div>}>
              <TerminalView enabled={session.terminal_enabled} />
            </Suspense>
          ) : snapshot ? (
            <>
              {activeView === 'overview' && (
                <Overview
                  snapshot={snapshot}
                  refreshing={refreshing}
                  busyTarget={busyTarget}
                  onRefresh={() => void loadDashboard(true)}
                  onRequestAction={(project, component, action) => setPendingAction({ project, component, action })}
                  onOpenLogs={openLogs}
                />
              )}
              {activeView === 'logs' && (
                <LogsView
                  projects={snapshot.projects}
                  initialSelection={logSelection}
                  onError={handleViewError}
                />
              )}
              {activeView === 'audit' && <AuditView onError={handleViewError} />}
            </>
          ) : refreshing ? (
            <div className="load-failure dashboard-loading" role="status">
              <LoaderCircle className="spin" size={28} />
              <strong>正在读取节点状态</strong>
              <span>正在汇总服务、容器与健康检查</span>
            </div>
          ) : (
            <div className="load-failure">
              <AlertTriangle size={28} />
              <strong>无法读取节点状态</strong>
              <span>{loadError || '状态服务暂时不可用'}</span>
              <button className="secondary-button" onClick={() => void loadDashboard(true)}>
                <RefreshCw size={16} />重试
              </button>
            </div>
          )}
        </main>
      </div>

      {pendingAction && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => !busyTarget && setPendingAction(null)}>
          <section
            className="confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className={`dialog-icon ${pendingAction.action}`}><AlertTriangle size={22} /></div>
            <div className="dialog-copy">
              <h2 id="confirm-title">确认{actionLabels[pendingAction.action]}组件</h2>
              <p>{pendingAction.project.name} / {pendingAction.component.label}</p>
              <span>操作会立即作用于服务器，并写入审计记录。</span>
            </div>
            <button
              className="icon-button dialog-close"
              onClick={() => setPendingAction(null)}
              disabled={Boolean(busyTarget)}
              title="关闭"
              aria-label="关闭"
            ><X size={17} /></button>
            <div className="dialog-actions">
              <button className="secondary-button" onClick={() => setPendingAction(null)} disabled={Boolean(busyTarget)} autoFocus>取消</button>
              <button
                className={`primary-button confirm-${pendingAction.action}`}
                onClick={() => void confirmAction()}
                disabled={Boolean(busyTarget)}
              >
                {busyTarget && <LoaderCircle className="spin" size={16} />}
                确认{actionLabels[pendingAction.action]}
              </button>
            </div>
          </section>
        </div>
      )}

      {toast && (
        <div className={`toast ${toast.tone}`} role="status">
          <span>{toast.message}</span>
          <button onClick={() => setToast(null)} title="关闭通知" aria-label="关闭通知"><X size={15} /></button>
        </div>
      )}
    </div>
  )
}
