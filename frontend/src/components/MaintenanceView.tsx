import { useCallback, useEffect, useState } from 'react'
import {
  CheckCircle2,
  HardDriveDownload,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { api, ApiError } from '../api'
import { formatBytes } from '../format'
import type { CleanupCandidate, MaintenanceDetails, OptimizationItem } from '../types'
import { OperationDialog } from './OperationDialog'

interface MaintenanceViewProps {
  csrfToken: string
  onError: (message: string, unauthorized?: boolean) => void
  onSuccess: (message: string) => void
}

type PendingMaintenance =
  | { kind: 'cleanup'; item: CleanupCandidate; action: string; label: string; token: string }
  | { kind: 'optimization'; item: OptimizationItem; action: string; label: string; token: string }

const riskLabels = { safe: '低风险', medium: '需确认', high: '仅展示' }

export function MaintenanceView({ csrfToken, onError, onSuccess }: MaintenanceViewProps) {
  const [details, setDetails] = useState<MaintenanceDetails | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<PendingMaintenance | null>(null)

  const loadMaintenance = useCallback(async () => {
    setLoading(true)
    try {
      setDetails(await api.maintenance())
    } catch (error) {
      onError(
        error instanceof Error ? error.message : '维护信息读取失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setLoading(false)
    }
  }, [onError])

  useEffect(() => {
    void loadMaintenance()
  }, [loadMaintenance])

  function queueOptimization(item: OptimizationItem) {
    if (!item.confirmation_action || !item.confirmation_token) return
    const applied = item.status === 'applied'
    setPending({
      kind: 'optimization',
      item,
      action: item.confirmation_action,
      label: applied ? '回退' : '应用',
      token: item.confirmation_token,
    })
  }

  async function confirmAction() {
    if (!pending) return
    setBusy(true)
    try {
      const result = pending.kind === 'cleanup'
        ? await api.maintenanceAction(csrfToken, pending.action, pending.token)
        : await api.optimizationAction(csrfToken, pending.action, pending.token)
      onSuccess(result.message)
      setPending(null)
      await loadMaintenance()
    } catch (error) {
      onError(
        error instanceof Error ? error.message : '维护操作失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setBusy(false)
    }
  }

  if (!details) return <div className="load-failure dashboard-loading"><LoaderCircle className="spin" size={28} /><strong>正在扫描维护项</strong></div>

  return (
    <section className="maintenance-view">
      <div className="view-toolbar management-toolbar">
        <div className="safety-indicator"><ShieldAlert size={17} /><strong>/data 与 Docker 数据卷受保护</strong></div>
        <div className="toolbar-spacer" />
        <button className="icon-button" onClick={() => void loadMaintenance()} disabled={loading} title="重新扫描" aria-label="重新扫描"><RefreshCw className={loading ? 'spin' : ''} size={17} /></button>
      </div>

      <div className="maintenance-grid">
        <section className="maintenance-section">
          <div className="section-heading"><HardDriveDownload size={18} /><div><strong>垃圾清理</strong><span>{details.cleanup.candidates.length} 个扫描项</span></div></div>
          <div className="maintenance-list">
            {details.cleanup.candidates.map((item) => <div className="maintenance-row" key={item.id}>
              <div className="maintenance-main"><strong>{item.label}</strong><span>{item.detail}</span></div>
              <span className={`risk-badge ${item.risk}`}>{riskLabels[item.risk]}</span>
              <strong className="reclaim-size">{formatBytes(item.size_bytes)}</strong>
              <button className="icon-button danger-icon" disabled={item.actionable === false || !item.confirmation_token} onClick={() => item.confirmation_token && setPending({ kind: 'cleanup', item, action: item.id, label: '清理', token: item.confirmation_token })} title={item.actionable === false ? '该项只展示，不允许自动删除' : '清理'} aria-label={`清理 ${item.label}`}><Trash2 size={16} /></button>
            </div>)}
          </div>
        </section>

        <section className="maintenance-section">
          <div className="section-heading"><Sparkles size={18} /><div><strong>系统优化</strong><span>可回滚设置</span></div></div>
          <div className="optimization-facts"><span>swappiness <strong>{details.optimization.facts.swappiness}</strong></span><span>可升级 <strong>{details.optimization.facts.updates}</strong></span><span>重启 <strong>{details.optimization.facts.reboot_required ? '需要' : '不需要'}</strong></span></div>
          <div className="maintenance-list">
            {details.optimization.recommendations.map((item) => {
              const applied = item.status === 'applied'
              const actionable = item.actionable !== false && ['enable-fstrim', 'limit-journal'].includes(item.id)
              return <div className="maintenance-row optimization-row" key={item.id}>
                <span className={`optimization-state ${item.status}`}>{applied || item.status === 'ok' ? <CheckCircle2 size={16} /> : <ShieldAlert size={16} />}</span>
                <div className="maintenance-main"><strong>{item.label}</strong><span>{item.detail}</span></div>
                <span className={`state-label ${applied || item.status === 'ok' ? 'healthy' : 'neutral'}`}>{applied ? '已应用' : item.status === 'recommended' ? '建议' : item.status === 'attention' ? '需关注' : '正常'}</span>
                {actionable && <button className="secondary-button compact-action" onClick={() => queueOptimization(item)}>{applied ? <RotateCcw size={15} /> : <Sparkles size={15} />}{applied ? '回退' : '应用'}</button>}
              </div>
            })}
          </div>
        </section>
      </div>

      {pending && <OperationDialog
        title={`确认${pending.label}${pending.kind === 'cleanup' ? '清理项' : '优化项'}`}
        target={pending.item.label}
        description={pending.kind === 'cleanup' ? `${pending.item.detail}；操作完成后无法由面板恢复。` : `${pending.item.detail}；该设置支持后续回退。`}
        confirmLabel={pending.label}
        tone={pending.kind === 'cleanup' ? 'danger' : 'default'}
        busy={busy}
        onClose={() => setPending(null)}
        onConfirm={() => void confirmAction()}
      />}
    </section>
  )
}
