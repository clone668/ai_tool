import { Fragment, useMemo, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  ExternalLink,
  HardDrive,
  MemoryStick,
  Play,
  RefreshCw,
  RotateCw,
  ScrollText,
  Search,
  Square,
  TimerReset,
  Workflow,
  X,
  Zap,
} from 'lucide-react'
import { actionLabels, formatBytes, formatUptime } from '../format'
import type {
  ActionName,
  Component,
  DashboardSnapshot,
  HealthStatus,
  Project,
} from '../types'
import { StatusBadge } from './StatusBadge'

interface OverviewProps {
  snapshot: DashboardSnapshot
  refreshing: boolean
  busyTarget: string | null
  onRefresh: () => void
  onRequestAction: (project: Project, component: Component, action: ActionName) => void
  onOpenLogs: (project: Project, component: Component) => void
}

type StatusFilter = 'all' | HealthStatus

function Metric({
  icon: Icon,
  label,
  value,
  detail,
  percent,
  tone,
}: {
  icon: typeof Zap
  label: string
  value: string
  detail: string
  percent?: number
  tone: string
}) {
  const safePercent = Math.max(0, Math.min(percent ?? 0, 100))
  return (
    <div className="metric">
      <div className={`metric-icon ${tone}`}><Icon size={19} /></div>
      <div className="metric-content">
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
        {percent != null && (
          <div className="metric-bar" aria-hidden="true">
            <span className={tone} style={{ width: `${safePercent}%` }} />
          </div>
        )}
      </div>
    </div>
  )
}

function ActionButtons({
  project,
  component,
  busy,
  onRequestAction,
  onOpenLogs,
}: {
  project: Project
  component: Component
  busy: boolean
  onRequestAction: OverviewProps['onRequestAction']
  onOpenLogs: OverviewProps['onOpenLogs']
}) {
  const icons = {
    start: Play,
    restart: RotateCw,
    stop: Square,
  }
  return (
    <div className="row-actions">
      <button
        className="icon-button"
        title={`查看 ${component.label} 日志`}
        aria-label={`查看 ${component.label} 日志`}
        onClick={(event) => {
          event.stopPropagation()
          onOpenLogs(project, component)
        }}
      >
        <ScrollText size={16} />
      </button>
      {component.actions.map((action) => {
        const Icon = icons[action]
        return (
          <button
            key={action}
            className={`icon-button action-${action}`}
            disabled={busy}
            title={`${actionLabels[action]} ${component.label}`}
            aria-label={`${actionLabels[action]} ${component.label}`}
            onClick={(event) => {
              event.stopPropagation()
              onRequestAction(project, component, action)
            }}
          >
            <Icon className={busy && action === 'restart' ? 'spin' : ''} size={16} />
          </button>
        )
      })}
    </div>
  )
}

function ComponentDetail({
  project,
  component,
  busyTarget,
  onRequestAction,
  onOpenLogs,
}: {
  project: Project
  component: Component
  busyTarget: string | null
  onRequestAction: OverviewProps['onRequestAction']
  onOpenLogs: OverviewProps['onOpenLogs']
}) {
  const target = `${project.id}/${component.id}`
  return (
    <div className="component-detail">
      <div className="component-main">
        <span className={`status-dot ${component.healthy ? 'healthy' : 'offline'}`} />
        <div>
          <strong>{component.label}</strong>
          <span>{component.type.replace('_', ' ')} · {component.state}/{component.substate}</span>
        </div>
      </div>
      <div className="component-facts">
        {component.pid != null && component.pid > 0 && <span>PID {component.pid}</span>}
        {component.memory_bytes != null && <span>{formatBytes(component.memory_bytes)}</span>}
        {component.children && <span>{component.children.length} 个容器</span>}
      </div>
      <ActionButtons
        project={project}
        component={component}
        busy={busyTarget === target}
        onRequestAction={onRequestAction}
        onOpenLogs={onOpenLogs}
      />
      {component.children && (
        <div className="container-list">
          {component.children.map((container) => (
            <div key={container.name} className="container-item">
              <span className={`status-dot ${container.healthy ? 'healthy' : 'offline'}`} />
              <strong>{container.name}</strong>
              <span>{container.state}</span>
              <span>{container.health ?? '无健康探针'}</span>
              <span>重启 {container.restart_count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ProjectTable({
  title,
  projects,
  expanded,
  busyTarget,
  onToggle,
  onRequestAction,
  onOpenLogs,
}: {
  title: string
  projects: Project[]
  expanded: Set<string>
  busyTarget: string | null
  onToggle: (projectId: string) => void
  onRequestAction: OverviewProps['onRequestAction']
  onOpenLogs: OverviewProps['onOpenLogs']
}) {
  if (!projects.length) return null
  return (
    <section className="project-section">
      <div className="section-heading">
        <h2>{title}</h2>
        <span>{projects.length}</span>
      </div>
      <div className="table-scroll">
        <table className="project-table">
          <colgroup>
            <col className="col-status" />
            <col className="col-project" />
            <col className="col-runtime" />
            <col className="col-components" />
            <col className="col-checks" />
            <col className="col-actions" />
          </colgroup>
          <thead>
            <tr>
              <th>状态</th>
              <th>项目</th>
              <th>运行方式</th>
              <th>组件</th>
              <th>健康检查</th>
              <th><span className="visually-hidden">操作</span></th>
            </tr>
          </thead>
          <tbody>
            {projects.map((project) => {
              const isExpanded = expanded.has(project.id)
              const primary = project.components.find((component) => component.actions.length) ?? project.components[0]
              const checksHealthy = project.checks.filter((check) => check.healthy).length
              return (
                <Fragment key={project.id}>
                  <tr className="project-row" onClick={() => onToggle(project.id)}>
                    <td data-label="状态"><StatusBadge status={project.status} /></td>
                    <td data-label="项目">
                      <div className="project-name-cell">
                        <button
                          className="expand-button"
                          aria-label={isExpanded ? `收起 ${project.name}` : `展开 ${project.name}`}
                          aria-expanded={isExpanded}
                          onClick={(event) => {
                            event.stopPropagation()
                            onToggle(project.id)
                          }}
                        >
                          {isExpanded ? <ChevronDown size={17} /> : <ChevronRight size={17} />}
                        </button>
                        <div>
                          <strong>{project.name}</strong>
                          <span>{project.description}</span>
                        </div>
                      </div>
                    </td>
                    <td data-label="运行方式">
                      <strong className="cell-primary">{project.runtime}</strong>
                      <span className="cell-secondary" title={project.path}>{project.path ?? '—'}</span>
                    </td>
                    <td data-label="组件">
                      <strong className="cell-primary">
                        {project.components.filter((component) => component.healthy).length}/{project.components.length} 正常
                      </strong>
                      <span className="cell-secondary">{project.components.map((component) => component.state).join(' · ')}</span>
                    </td>
                    <td data-label="健康检查">
                      <strong className="cell-primary">
                        {project.checks.length ? `${checksHealthy}/${project.checks.length} 通过` : '仅进程状态'}
                      </strong>
                      <span className="cell-secondary">
                        {project.checks.length
                          ? `${Math.max(...project.checks.map((check) => check.latency_ms))} ms`
                          : '—'}
                      </span>
                    </td>
                    <td data-label="操作">
                      <div className="row-action-wrap">
                        {project.url && (
                          <a
                            className="icon-button"
                            href={project.url}
                            target="_blank"
                            rel="noreferrer"
                            title={`打开 ${project.name}`}
                            aria-label={`打开 ${project.name}`}
                            onClick={(event) => event.stopPropagation()}
                          >
                            <ExternalLink size={16} />
                          </a>
                        )}
                        <ActionButtons
                          project={project}
                          component={primary}
                          busy={busyTarget === `${project.id}/${primary.id}`}
                          onRequestAction={onRequestAction}
                          onOpenLogs={onOpenLogs}
                        />
                      </div>
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr className="project-expanded-row">
                      <td colSpan={6}>
                        <div className="project-expanded">
                          <div className="detail-column">
                            <h3>运行组件</h3>
                            {project.components.map((component) => (
                              <ComponentDetail
                                key={component.id}
                                project={project}
                                component={component}
                                busyTarget={busyTarget}
                                onRequestAction={onRequestAction}
                                onOpenLogs={onOpenLogs}
                              />
                            ))}
                          </div>
                          <div className="detail-column checks-column">
                            <h3>健康检查</h3>
                            {project.checks.length ? project.checks.map((check) => (
                              <div className="check-item" key={check.id}>
                                <span className={`status-dot ${check.healthy ? 'healthy' : 'offline'}`} />
                                <div>
                                  <strong>{check.label}</strong>
                                  <span>{check.detail}</span>
                                </div>
                                <strong>{check.latency_ms} ms</strong>
                              </div>
                            )) : <span className="empty-inline">未配置网络探针</span>}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export function Overview({
  snapshot,
  refreshing,
  busyTarget,
  onRefresh,
  onRequestAction,
  onOpenLogs,
}: OverviewProps) {
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    return snapshot.projects.filter((project) => {
      const statusMatches = statusFilter === 'all' || project.status === statusFilter
      const textMatches = !normalized || [project.name, project.description, project.runtime, project.path]
        .filter(Boolean)
        .some((value) => value!.toLowerCase().includes(normalized))
      return statusMatches && textMatches
    })
  }, [query, snapshot.projects, statusFilter])

  function toggle(projectId: string) {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(projectId)) next.delete(projectId)
      else next.add(projectId)
      return next
    })
  }

  const applications = filtered.filter((project) => project.kind === 'application')
  const infrastructure = filtered.filter((project) => project.kind === 'infrastructure')
  const scheduled = filtered.filter((project) => project.kind === 'scheduled')
  const host = snapshot.host

  return (
    <div className="overview-view">
      <div className="metrics-band">
        <Metric
          icon={Zap}
          label="CPU"
          value={`${host.cpu_percent.toFixed(1)}%`}
          detail={`负载 ${host.load_average.map((value) => value.toFixed(2)).join(' / ')}`}
          percent={host.cpu_percent}
          tone="blue"
        />
        <Metric
          icon={MemoryStick}
          label="内存"
          value={`${host.memory_percent.toFixed(1)}%`}
          detail={`${formatBytes(host.memory_used)} / ${formatBytes(host.memory_total)}`}
          percent={host.memory_percent}
          tone="green"
        />
        <Metric
          icon={HardDrive}
          label="数据盘 /data"
          value={`${host.disk_percent.toFixed(1)}%`}
          detail={`${formatBytes(host.disk_used)} / ${formatBytes(host.disk_total)}`}
          percent={host.disk_percent}
          tone="amber"
        />
        <Metric
          icon={TimerReset}
          label="运行时间"
          value={formatUptime(host.uptime_seconds)}
          detail={host.platform}
          tone="neutral"
        />
      </div>

      <div className="project-toolbar">
        <div className="summary-line">
          <Workflow size={18} />
          <strong>{snapshot.summary.healthy}/{snapshot.summary.total}</strong>
          <span>应用运行正常</span>
          {snapshot.summary.degraded > 0 && <span className="summary-warning">{snapshot.summary.degraded} 个需关注</span>}
          {snapshot.summary.offline > 0 && <span className="summary-danger">{snapshot.summary.offline} 个离线</span>}
        </div>
        <div className="toolbar-controls">
          <div className="search-field">
            <Search size={16} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索项目"
              aria-label="搜索项目"
            />
            {query && (
              <button onClick={() => setQuery('')} title="清除搜索" aria-label="清除搜索"><X size={15} /></button>
            )}
          </div>
          <div className="segmented-control" aria-label="状态筛选">
            {([
              ['all', '全部'],
              ['healthy', '正常'],
              ['degraded', '关注'],
              ['offline', '离线'],
            ] as [StatusFilter, string][]).map(([value, label]) => (
              <button
                key={value}
                className={statusFilter === value ? 'active' : ''}
                onClick={() => setStatusFilter(value)}
              >{label}</button>
            ))}
          </div>
          <button className="icon-button refresh-button" onClick={onRefresh} disabled={refreshing} title="立即刷新" aria-label="立即刷新">
            <RefreshCw className={refreshing ? 'spin' : ''} size={17} />
          </button>
        </div>
      </div>

      {filtered.length ? (
        <>
          <ProjectTable
            title="应用项目"
            projects={applications}
            expanded={expanded}
            busyTarget={busyTarget}
            onToggle={toggle}
            onRequestAction={onRequestAction}
            onOpenLogs={onOpenLogs}
          />
          <ProjectTable
            title="基础设施"
            projects={infrastructure}
            expanded={expanded}
            busyTarget={busyTarget}
            onToggle={toggle}
            onRequestAction={onRequestAction}
            onOpenLogs={onOpenLogs}
          />
          <ProjectTable
            title="定时任务"
            projects={scheduled}
            expanded={expanded}
            busyTarget={busyTarget}
            onToggle={toggle}
            onRequestAction={onRequestAction}
            onOpenLogs={onOpenLogs}
          />
        </>
      ) : (
        <div className="empty-state">
          <Search size={24} />
          <strong>没有符合条件的项目</strong>
          <span>调整搜索词或状态筛选</span>
        </div>
      )}
    </div>
  )
}
