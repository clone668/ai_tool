import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, CircleX, History, RefreshCw, ShieldAlert } from 'lucide-react'
import { api } from '../api'
import { actionLabels, formatDate } from '../format'
import type { ActionName, AuditItem } from '../types'

interface AuditViewProps {
  onError: (message: string, unauthorized?: boolean) => void
}

type OutcomeFilter = 'all' | AuditItem['outcome']

const outcomeLabels: Record<AuditItem['outcome'], string> = {
  success: '成功',
  failed: '失败',
  denied: '拒绝',
}

export function AuditView({ onError }: AuditViewProps) {
  const [items, setItems] = useState<AuditItem[]>([])
  const [loading, setLoading] = useState(false)
  const [outcome, setOutcome] = useState<OutcomeFilter>('all')

  const loadAudit = useCallback(async () => {
    setLoading(true)
    try {
      const result = await api.audit()
      setItems(result.items)
    } catch (error) {
      const message = error instanceof Error ? error.message : '审计记录读取失败'
      const unauthorized = error instanceof Error && 'status' in error && error.status === 401
      onError(message, unauthorized)
    } finally {
      setLoading(false)
    }
  }, [onError])

  useEffect(() => {
    void loadAudit()
  }, [loadAudit])

  const filtered = useMemo(
    () => items.filter((item) => outcome === 'all' || item.outcome === outcome),
    [items, outcome],
  )

  function outcomeIcon(value: AuditItem['outcome']) {
    if (value === 'success') return <CheckCircle2 size={16} />
    if (value === 'denied') return <ShieldAlert size={16} />
    return <CircleX size={16} />
  }

  function actionLabel(value: string) {
    if (value in actionLabels) return actionLabels[value as ActionName]
    return value === 'login' ? '登录' : value === 'logout' ? '退出' : value
  }

  return (
    <section className="audit-view">
      <div className="view-toolbar audit-toolbar">
        <div className="segmented-control" aria-label="审计结果筛选">
          {([
            ['all', '全部'],
            ['success', '成功'],
            ['failed', '失败'],
            ['denied', '拒绝'],
          ] as [OutcomeFilter, string][]).map(([value, label]) => (
            <button key={value} className={outcome === value ? 'active' : ''} onClick={() => setOutcome(value)}>{label}</button>
          ))}
        </div>
        <span className="record-count">{filtered.length} 条记录</span>
        <div className="toolbar-spacer" />
        <button className="icon-button" onClick={() => void loadAudit()} disabled={loading} title="刷新审计记录" aria-label="刷新审计记录">
          <RefreshCw className={loading ? 'spin' : ''} size={17} />
        </button>
      </div>
      <div className="table-scroll audit-table-wrap">
        <table className="audit-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>结果</th>
              <th>操作</th>
              <th>目标</th>
              <th>用户</th>
              <th>来源</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((item) => (
              <tr key={item.id}>
                <td>{formatDate(item.created_at)}</td>
                <td><span className={`audit-outcome ${item.outcome}`}>{outcomeIcon(item.outcome)}{outcomeLabels[item.outcome]}</span></td>
                <td><strong>{actionLabel(item.action)}</strong></td>
                <td>{item.project_id ? `${item.project_id}${item.component_id ? ` / ${item.component_id}` : ''}` : '控制台'}</td>
                <td>{item.username}</td>
                <td>{item.ip_address}</td>
                <td className="audit-detail" title={item.detail}>{item.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length && (
          <div className="empty-state compact">
            <History size={22} />
            <strong>暂无审计记录</strong>
          </div>
        )}
      </div>
    </section>
  )
}
