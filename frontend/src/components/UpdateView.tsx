import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowUpCircle,
  CheckCircle2,
  CircleX,
  GitBranch,
  LoaderCircle,
  RefreshCw,
  Rocket,
} from 'lucide-react'
import { api, ApiError } from '../api'
import type { UpdateStatus } from '../types'

interface UpdateViewProps {
  csrfToken: string
  onError: (message: string, unauthorized?: boolean) => void
  onSuccess: (message: string) => void
}

export function UpdateView({ csrfToken, onError, onSuccess }: UpdateViewProps) {
  const [status, setStatus] = useState<UpdateStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [checking, setChecking] = useState(false)
  const [starting, setStarting] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [finished, setFinished] = useState<UpdateStatus['last_run'] | null>(null)
  const wasRunning = useRef(false)

  const load = useCallback(async (refresh: boolean) => {
    try {
      const result = await api.updateStatus(refresh)
      setStatus(result)
      if (wasRunning.current && !result.running && result.last_run) {
        setFinished(result.last_run)
        if (result.last_run.status !== 'success') {
          onError(result.last_run.message || '更新失败')
        }
      }
      wasRunning.current = result.running
      return result
    } catch (error) {
      // During an update the service restarts: connection failures are expected.
      if (wasRunning.current) return null
      const message = error instanceof Error ? error.message : '更新状态读取失败'
      onError(message, error instanceof ApiError && error.status === 401)
      return null
    }
  }, [onError])

  useEffect(() => {
    setLoading(true)
    void load(false).finally(() => setLoading(false))
    const timer = window.setInterval(() => void load(false), 4000)
    return () => window.clearInterval(timer)
  }, [load])

  async function checkUpdates() {
    setChecking(true)
    try {
      const result = await api.updateStatus(true)
      setStatus(result)
      onSuccess(result.update_available ? `发现 ${result.behind} 个新提交` : '已是最新版本')
    } catch (error) {
      onError(error instanceof Error ? error.message : '检查更新失败')
    } finally {
      setChecking(false)
    }
  }

  async function applyUpdate() {
    setStarting(true)
    try {
      const result = await api.updateApply(csrfToken)
      onSuccess(result.message)
      setConfirming(false)
      setFinished(null)
      wasRunning.current = true
      await load(false)
    } catch (error) {
      onError(error instanceof Error ? error.message : '启动更新失败')
    } finally {
      setStarting(false)
    }
  }

  const running = Boolean(status?.running) || starting
  const lastRun = finished ?? status?.last_run ?? null

  return (
    <section className="update-view">
      <div className="view-toolbar">
        <span className="record-count">
          {status ? `${status.branch} ${status.upstream ? `→ ${status.upstream}` : ''}` : ''}
        </span>
        <div className="toolbar-spacer" />
        <button className="secondary-button" onClick={() => void checkUpdates()} disabled={checking || running}>
          {checking ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}
          检查更新
        </button>
        <button
          className="primary-button"
          onClick={() => setConfirming(true)}
          disabled={!status?.update_available || running}
          title={status?.update_available ? '拉取最新代码并重新部署' : '当前已是最新'}
        >
          {running ? <LoaderCircle className="spin" size={16} /> : <ArrowUpCircle size={16} />}
          立即更新
        </button>
      </div>

      {loading && !status ? (
        <div className="load-failure dashboard-loading" role="status">
          <LoaderCircle className="spin" size={28} />
          <strong>正在读取版本信息</strong>
        </div>
      ) : status ? (
        <div className="update-cards">
          <div className="panel update-card">
            <div className="update-card-head">
              <GitBranch size={18} />
              <strong>当前版本</strong>
            </div>
            {status.current.available ? (
              <>
                <code>{status.current.short}</code>
                <span>{status.current.subject}</span>
                <small>{status.current.time}</small>
              </>
            ) : (
              <span>无法读取当前提交</span>
            )}
          </div>

          <div className="panel update-card">
            <div className="update-card-head">
              <Rocket size={18} />
              <strong>远端版本</strong>
            </div>
            {status.remote.available ? (
              <>
                <code>{status.remote.short}</code>
                <span>{status.remote.subject}</span>
                <small>{status.remote.time}</small>
              </>
            ) : (
              <span>{status.upstream ? '无法读取远端提交' : '未配置上游分支'}</span>
            )}
            {status.fetch_error && <small className="update-warning">拉取远端信息失败：{status.fetch_error}</small>}
          </div>

          <div className="panel update-card">
            <div className="update-card-head">
              {running ? (
                <LoaderCircle className="spin" size={18} />
              ) : lastRun?.status === 'success' ? (
                <CheckCircle2 size={18} />
              ) : lastRun?.status === 'failed' ? (
                <CircleX size={18} />
              ) : (
                <ArrowUpCircle size={18} />
              )}
              <strong>更新状态</strong>
            </div>
            {running ? (
              <>
                <span>更新进行中，服务会自动重启，页面可能短暂断开</span>
                <small>请勿关闭本页，完成后会提示刷新</small>
              </>
            ) : lastRun?.status ? (
              <>
                <span>{lastRun.message}</span>
                <small>
                  {lastRun.finished_at ? new Date(lastRun.finished_at).toLocaleString() : ''}
                  {lastRun.to_commit ? ` · ${lastRun.to_commit.slice(0, 7)}` : ''}
                </small>
                {lastRun.status === 'success' && (
                  <button className="primary-button" onClick={() => window.location.reload()}>
                    <RefreshCw size={16} />
                    刷新页面加载新版本
                  </button>
                )}
              </>
            ) : (
              <span>
                {status.update_available
                  ? `落后远端 ${status.behind} 个提交，可以更新`
                  : '当前已是最新版本'}
              </span>
            )}
          </div>
        </div>
      ) : (
        <div className="load-failure">
          <CircleX size={28} />
          <strong>无法读取版本信息</strong>
          <button className="secondary-button" onClick={() => void load(false)}>
            <RefreshCw size={16} />重试
          </button>
        </div>
      )}

      {confirming && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => !starting && setConfirming(false)}>
          <section
            className="confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="update-confirm-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="dialog-icon restart"><ArrowUpCircle size={22} /></div>
            <div className="dialog-copy">
              <h2 id="update-confirm-title">确认更新 AI Tool</h2>
              <p>将从 {status?.upstream ?? '远端'} 拉取 {status?.behind ?? 0} 个提交并重新部署</p>
              <span>更新期间服务会重启，操作会写入审计记录。</span>
            </div>
            <div className="dialog-actions">
              <button className="secondary-button" onClick={() => setConfirming(false)} disabled={starting} autoFocus>取消</button>
              <button className="primary-button" onClick={() => void applyUpdate()} disabled={starting}>
                {starting && <LoaderCircle className="spin" size={16} />}
                确认更新
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  )
}
