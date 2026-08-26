import { useCallback, useEffect, useMemo, useState } from 'react'
import { Boxes, LoaderCircle, Play, RefreshCw, RotateCw, Search, Square } from 'lucide-react'
import { api, ApiError } from '../api'
import type { StartupAction, StartupInventory, StartupItem, StartupScope } from '../types'
import { OperationDialog } from './OperationDialog'

interface StartupViewProps {
  csrfToken: string
  onError: (message: string, unauthorized?: boolean) => void
  onSuccess: (message: string) => void
}

interface PendingStartupAction {
  item: StartupItem
  action: StartupAction
  value: string
}

const scopeLabels: Record<StartupScope, string> = {
  system: '系统服务',
  user: '用户服务',
  docker: 'Docker',
}

const actionLabels: Record<StartupAction, string> = {
  start: '启动',
  stop: '停止',
  restart: '重启',
  enable: '启用自启动',
  disable: '禁用自启动',
  policy: '修改重启策略',
}

export function StartupView({ csrfToken, onError, onSuccess }: StartupViewProps) {
  const [inventory, setInventory] = useState<StartupInventory | null>(null)
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [scope, setScope] = useState<'all' | StartupScope>('all')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<PendingStartupAction | null>(null)

  const loadStartup = useCallback(async () => {
    setLoading(true)
    try {
      setInventory(await api.startup(submittedQuery))
    } catch (error) {
      onError(
        error instanceof Error ? error.message : '自启动清单读取失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setLoading(false)
    }
  }, [onError, submittedQuery])

  useEffect(() => {
    void loadStartup()
  }, [loadStartup])

  const items = useMemo(
    () => (inventory?.items ?? []).filter((item) => scope === 'all' || item.scope === scope),
    [inventory, scope],
  )

  function queue(item: StartupItem, action: StartupAction, value = '_') {
    setPending({ item, action, value })
  }

  async function confirmAction() {
    if (!pending) return
    setBusy(true)
    try {
      const result = await api.startupAction(
        csrfToken,
        pending.item.scope,
        pending.item.name,
        pending.action,
        pending.value,
      )
      onSuccess(result.message)
      setPending(null)
      await loadStartup()
    } catch (error) {
      onError(
        error instanceof Error ? error.message : '自启动操作失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="management-view">
      <div className="view-toolbar management-toolbar">
        <form className="management-search" onSubmit={(event) => {
          event.preventDefault()
          const normalized = query.trim()
          setSubmittedQuery(normalized)
          if (normalized === submittedQuery) void loadStartup()
        }}>
          <Search size={16} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="服务或容器名称" aria-label="搜索自启动项" />
          <button className="secondary-button" type="submit">搜索</button>
        </form>
        <div className="segmented-control" aria-label="自启动类型">
          {([
            ['all', '全部'],
            ['system', '系统'],
            ['user', '用户'],
            ['docker', 'Docker'],
          ] as const).map(([value, label]) => (
            <button key={value} className={scope === value ? 'active' : ''} onClick={() => setScope(value)}>{label}</button>
          ))}
        </div>
        <div className="toolbar-spacer" />
        <span className="record-count">{inventory?.total ?? 0} 项</span>
        <button className="icon-button" onClick={() => void loadStartup()} disabled={loading} title="刷新自启动清单" aria-label="刷新自启动清单"><RefreshCw className={loading ? 'spin' : ''} size={17} /></button>
      </div>

      <div className="table-scroll management-table-wrap">
        <table className="management-table startup-table">
          <thead><tr><th>名称</th><th>范围</th><th>运行状态</th><th>开机策略</th><th>启用</th><th>运行操作</th></tr></thead>
          <tbody>
            {items.map((item) => {
              const running = item.active_state === 'active' || item.active_state === 'running'
              const enabled = ['enabled', 'enabled-runtime', 'always', 'unless-stopped', 'on-failure'].includes(item.enabled_state)
              return (
                <tr key={`${item.scope}:${item.name}`}>
                  <td><div className="primary-cell"><Boxes size={17} /><div><strong>{item.name}</strong><span>{item.substate}</span></div></div></td>
                  <td>{scopeLabels[item.scope]}</td>
                  <td><span className={`state-label ${running ? 'healthy' : 'neutral'}`}>{item.active_state}</span></td>
                  <td>
                    {item.scope === 'docker' ? (
                      <select className="inline-select" value={item.enabled_state || 'no'} onChange={(event) => queue(item, 'policy', event.target.value)} aria-label={`${item.name} 重启策略`}>
                        {['no', 'always', 'unless-stopped', 'on-failure'].map((value) => <option key={value} value={value}>{value}</option>)}
                      </select>
                    ) : item.enabled_state}
                  </td>
                  <td>
                    {item.scope === 'docker' ? <span className="muted-cell">按策略</span> : (
                      <label className="switch-control compact-switch" title={item.protected ? '受保护服务不能禁用' : '切换开机启动'}>
                        <input type="checkbox" checked={enabled} disabled={item.protected && enabled} onChange={() => queue(item, enabled ? 'disable' : 'enable')} />
                        <span className="switch-track" aria-hidden="true"><span /></span>
                      </label>
                    )}
                  </td>
                  <td><div className="row-tools">
                    <button className="icon-button" onClick={() => queue(item, running ? 'stop' : 'start')} disabled={item.protected && running} title={running ? '停止' : '启动'} aria-label={`${running ? '停止' : '启动'} ${item.name}`}>{running ? <Square size={15} /> : <Play size={16} />}</button>
                    <button className="icon-button" onClick={() => queue(item, 'restart')} title="重启" aria-label={`重启 ${item.name}`}><RotateCw size={16} /></button>
                  </div></td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {!items.length && <div className="empty-state compact">{loading ? <LoaderCircle className="spin" size={22} /> : <Boxes size={22} />}<strong>{loading ? '正在读取自启动清单' : '没有匹配的项目'}</strong></div>}
      </div>

      {pending && (
        <OperationDialog
          title={`确认${actionLabels[pending.action]}`}
          target={`${scopeLabels[pending.item.scope]} / ${pending.item.name}`}
          description={pending.action === 'policy' ? `重启策略将改为 ${pending.value}` : '操作会立即作用于 systemd 或 Docker，并写入审计记录。'}
          confirmLabel={actionLabels[pending.action]}
          tone={pending.action === 'stop' || pending.action === 'disable' ? 'danger' : 'default'}
          busy={busy}
          onClose={() => setPending(null)}
          onConfirm={() => void confirmAction()}
        />
      )}
    </section>
  )
}
