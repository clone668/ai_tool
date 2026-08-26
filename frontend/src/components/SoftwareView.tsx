import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowUpCircle,
  Download,
  LoaderCircle,
  PackageSearch,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { api, ApiError } from '../api'
import { formatBytes } from '../format'
import type {
  PackageManager,
  SoftwareAction,
  SoftwareInventory,
  SoftwareItem,
  SoftwarePlan,
} from '../types'
import { OperationDialog } from './OperationDialog'

interface SoftwareViewProps {
  csrfToken: string
  onError: (message: string, unauthorized?: boolean) => void
  onSuccess: (message: string) => void
}

interface PendingSoftwareAction {
  manager: PackageManager
  name: string
  action: SoftwareAction
}

const actionText: Record<SoftwareAction, string> = {
  install: '安装',
  upgrade: '升级',
  remove: '卸载',
  purge: '彻底卸载',
  refresh: '刷新索引',
}

export function SoftwareView({ csrfToken, onError, onSuccess }: SoftwareViewProps) {
  const [inventory, setInventory] = useState<SoftwareInventory | null>(null)
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [manager, setManager] = useState<'all' | PackageManager>('all')
  const [stateFilter, setStateFilter] = useState<'all' | 'installed' | 'available'>('all')
  const [loading, setLoading] = useState(false)
  const [pending, setPending] = useState<PendingSoftwareAction | null>(null)
  const [plan, setPlan] = useState<SoftwarePlan | null>(null)
  const [planning, setPlanning] = useState(false)
  const [acting, setActing] = useState(false)

  const loadSoftware = useCallback(async (search = submittedQuery) => {
    setLoading(true)
    try {
      setInventory(await api.software(search))
    } catch (error) {
      onError(
        error instanceof Error ? error.message : '软件清单读取失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setLoading(false)
    }
  }, [onError, submittedQuery])

  useEffect(() => {
    void loadSoftware()
  }, [loadSoftware])

  const items = useMemo(() => (inventory?.items ?? []).filter((item) => {
    if (manager !== 'all' && item.manager !== manager) return false
    if (stateFilter === 'installed' && !item.installed) return false
    if (stateFilter === 'available' && item.installed) return false
    return true
  }), [inventory, manager, stateFilter])

  async function requestAction(item: SoftwareItem, action: SoftwareAction) {
    const next = { manager: item.manager, name: item.name, action }
    setPending(next)
    setPlan(null)
    setPlanning(true)
    try {
      setPlan(await api.softwarePlan(csrfToken, item.manager, item.name, action))
    } catch (error) {
      setPending(null)
      onError(
        error instanceof Error ? error.message : '操作预览失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setPlanning(false)
    }
  }

  async function requestRefresh(managerValue: PackageManager) {
    await requestAction({
      manager: managerValue,
      name: '_',
      version: null,
      size_bytes: null,
      installed: false,
      description: '',
      protected: false,
    }, 'refresh')
  }

  async function confirmAction() {
    if (!pending || !plan) return
    setActing(true)
    try {
      const result = await api.softwareAction(
        csrfToken,
        pending.manager,
        pending.name,
        pending.action,
        plan.confirmation_token,
      )
      onSuccess(result.message)
      setPending(null)
      setPlan(null)
      await loadSoftware()
    } catch (error) {
      onError(
        error instanceof Error ? error.message : '软件操作失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setActing(false)
    }
  }

  function submitSearch(event: React.FormEvent) {
    event.preventDefault()
    const normalized = query.trim()
    setSubmittedQuery(normalized)
    if (normalized === submittedQuery) void loadSoftware(normalized)
  }

  return (
    <section className="management-view">
      <div className="view-toolbar management-toolbar">
        <form className="management-search" onSubmit={submitSearch}>
          <Search size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="软件包名称"
            aria-label="搜索软件包"
          />
          <button className="secondary-button" type="submit">搜索</button>
        </form>
        <div className="segmented-control" aria-label="软件来源">
          {(['all', 'apt', 'snap'] as const).map((value) => (
            <button key={value} className={manager === value ? 'active' : ''} onClick={() => setManager(value)}>
              {value === 'all' ? '全部' : value.toUpperCase()}
            </button>
          ))}
        </div>
        <div className="toolbar-spacer" />
        <button className="secondary-button" onClick={() => void requestRefresh('apt')}>
          <RefreshCw size={16} />刷新 APT 索引
        </button>
        <button className="icon-button" onClick={() => void loadSoftware()} disabled={loading} title="刷新清单" aria-label="刷新清单">
          <RefreshCw className={loading ? 'spin' : ''} size={17} />
        </button>
      </div>

      <div className="section-strip">
        <div>
          <strong>{inventory?.counts.installed ?? 0}</strong>
          <span>已安装</span>
        </div>
        <div>
          <strong>{inventory?.counts.available ?? 0}</strong>
          <span>搜索结果</span>
        </div>
        <div className="segmented-control compact-segments" aria-label="安装状态">
          {([
            ['all', '全部'],
            ['installed', '已安装'],
            ['available', '可安装'],
          ] as const).map(([value, label]) => (
            <button key={value} className={stateFilter === value ? 'active' : ''} onClick={() => setStateFilter(value)}>{label}</button>
          ))}
        </div>
      </div>

      <div className="table-scroll management-table-wrap">
        <table className="management-table software-table">
          <thead><tr><th>软件包</th><th>来源</th><th>版本</th><th>架构 / 通道</th><th>大小</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.manager}:${item.name}`}>
                <td><div className="primary-cell"><PackageSearch size={17} /><div><strong>{item.name}</strong><span>{item.description || '—'}</span></div></div></td>
                <td><span className="source-chip">{item.manager.toUpperCase()}</span></td>
                <td className="mono-cell">{item.version || '—'}</td>
                <td>{item.architecture || item.tracking || '—'}</td>
                <td>{formatBytes(item.size_bytes)}</td>
                <td>{item.protected ? <span className="protected-label"><ShieldCheck size={14} />系统保护</span> : item.installed ? <span className="state-label healthy">已安装</span> : <span className="state-label neutral">可安装</span>}</td>
                <td>
                  <div className="row-tools">
                    {!item.installed && <button className="icon-button" onClick={() => void requestAction(item, 'install')} title="安装" aria-label={`安装 ${item.name}`}><Download size={16} /></button>}
                    {item.installed && <button className="icon-button" onClick={() => void requestAction(item, item.manager === 'apt' ? 'upgrade' : 'refresh')} title="升级" aria-label={`升级 ${item.name}`}><ArrowUpCircle size={16} /></button>}
                    {item.installed && <button className="icon-button danger-icon" onClick={() => void requestAction(item, 'remove')} disabled={item.protected} title={item.protected ? '受保护的软件包不能卸载' : '卸载'} aria-label={`卸载 ${item.name}`}><Trash2 size={16} /></button>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!items.length && <div className="empty-state compact">{loading ? <LoaderCircle className="spin" size={22} /> : <PackageSearch size={22} />}<strong>{loading ? '正在读取软件清单' : '没有匹配的软件包'}</strong></div>}
      </div>

      {pending && (
        <OperationDialog
          title={`确认${actionText[pending.action]}`}
          target={`${pending.manager.toUpperCase()} / ${pending.name === '_' ? '软件索引' : pending.name}`}
          description="执行前已由系统包管理器生成变更预览，确认后会立即作用于服务器。"
          confirmLabel={actionText[pending.action]}
          tone={pending.action === 'remove' || pending.action === 'purge' ? 'danger' : 'default'}
          busy={acting || planning}
          onClose={() => { setPending(null); setPlan(null) }}
          onConfirm={() => void confirmAction()}
        >
          {planning ? <div className="inline-loading"><LoaderCircle className="spin" size={16} />生成预览</div> : (
            <pre>{plan?.summary || plan?.changes.join('\n') || '没有额外依赖变更。'}</pre>
          )}
        </OperationDialog>
      )}
    </section>
  )
}
