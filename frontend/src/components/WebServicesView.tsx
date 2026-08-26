import { useCallback, useEffect, useState } from 'react'
import {
  AppWindow,
  Container,
  ExternalLink,
  FileText,
  Globe2,
  LoaderCircle,
  Network,
  Pencil,
  Plus,
  RefreshCw,
  RotateCw,
  Save,
  Server,
  TriangleAlert,
  Trash2,
  X,
} from 'lucide-react'
import { api, ApiError } from '../api'
import type { DiscoveredWebService, WebInventory, WebService } from '../types'
import { OperationDialog } from './OperationDialog'

interface WebServicesViewProps {
  csrfToken: string
  onError: (message: string, unauthorized?: boolean) => void
  onSuccess: (message: string) => void
}

interface PendingWebAction {
  service: WebService
  action: 'enable' | 'disable' | 'delete' | 'reload'
}

const emptyService: WebService = {
  id: '',
  name: '',
  domain: '',
  upstream_host: '127.0.0.1',
  upstream_port: 3000,
  websocket: true,
  enabled: true,
}

const webActionLabels = {
  enable: '启用入口',
  disable: '禁用入口',
  delete: '删除入口',
  reload: '重载配置',
}

const sourceLabels: Record<DiscoveredWebService['source'], string> = {
  nginx: 'Nginx',
  docker: 'Docker',
  systemd: 'systemd',
  project: '项目清单',
  process: '系统进程',
}

function SourceIcon({ source }: { source: DiscoveredWebService['source'] }) {
  if (source === 'docker') return <Container size={17} />
  if (source === 'nginx') return <Globe2 size={17} />
  if (source === 'systemd') return <Server size={17} />
  return <Network size={17} />
}

export function WebServicesView({ csrfToken, onError, onSuccess }: WebServicesViewProps) {
  const [inventory, setInventory] = useState<WebInventory | null>(null)
  const [mode, setMode] = useState<'discovered' | 'managed'>('discovered')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [editor, setEditor] = useState<WebService | null>(null)
  const [originalId, setOriginalId] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingWebAction | null>(null)
  const [logTarget, setLogTarget] = useState<WebService | null>(null)
  const [logStream, setLogStream] = useState<'access' | 'error'>('access')
  const [logContent, setLogContent] = useState('')
  const [logLoading, setLogLoading] = useState(false)

  const loadInventory = useCallback(async () => {
    setLoading(true)
    try {
      setInventory(await api.webServices())
    } catch (error) {
      onError(
        error instanceof Error ? error.message : 'Web 服务读取失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setLoading(false)
    }
  }, [onError])

  useEffect(() => {
    void loadInventory()
  }, [loadInventory])

  const loadLogs = useCallback(async (service: WebService, stream: 'access' | 'error') => {
    setLogLoading(true)
    try {
      setLogContent((await api.webServiceLogs(service.id, stream)).content)
    } catch (error) {
      onError(
        error instanceof Error ? error.message : 'Nginx 日志读取失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setLogLoading(false)
    }
  }, [onError])

  function openLogs(service: WebService) {
    setLogTarget(service)
    setLogStream('access')
    setLogContent('')
    void loadLogs(service, 'access')
  }

  function createManagedEntry(service: DiscoveredWebService) {
    if (!service.suggested_service) return
    setEditor({ ...service.suggested_service })
    setOriginalId(null)
  }

  async function saveService(event: React.FormEvent) {
    event.preventDefault()
    if (!editor) return
    setBusy(true)
    try {
      const result = await api.saveWebService(csrfToken, editor)
      onSuccess(result.message)
      setEditor(null)
      setOriginalId(null)
      setMode('managed')
      await loadInventory()
    } catch (error) {
      onError(
        error instanceof Error ? error.message : 'Web 服务保存失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setBusy(false)
    }
  }

  async function confirmAction() {
    if (!pending) return
    setBusy(true)
    try {
      const result = await api.webServiceAction(csrfToken, pending.service.id, pending.action)
      onSuccess(result.message)
      setPending(null)
      await loadInventory()
    } catch (error) {
      onError(
        error instanceof Error ? error.message : 'Web 服务操作失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="management-view web-services-view">
      <div className="view-toolbar management-toolbar">
        <div className={`nginx-state ${inventory?.nginx_active ? 'healthy' : 'offline'}`}><span className="status-dot" /><div><strong>Nginx</strong><span>{inventory?.nginx_active ? '运行中' : '未运行'}</span></div></div>
        <div className="segmented-control compact-segments web-mode-tabs">
          <button className={mode === 'discovered' ? 'active' : ''} onClick={() => setMode('discovered')}>自动发现 <span>{inventory?.discovered.length ?? 0}</span></button>
          <button className={mode === 'managed' ? 'active' : ''} onClick={() => setMode('managed')}>托管入口 <span>{inventory?.items.length ?? 0}</span></button>
        </div>
        <div className="toolbar-spacer" />
        <button className="primary-button" onClick={() => { setEditor({ ...emptyService }); setOriginalId(null) }}><Plus size={16} />新增入口</button>
        <button className="icon-button" onClick={() => void loadInventory()} disabled={loading} title="刷新 Web 服务" aria-label="刷新 Web 服务"><RefreshCw className={loading ? 'spin' : ''} size={17} /></button>
      </div>

      {inventory?.warnings.length ? <div className="web-discovery-warning" role="status"><TriangleAlert size={16} /><span>{inventory.warnings.join('；')}</span></div> : null}

      {mode === 'discovered' && <div className="table-scroll management-table-wrap">
        <table className="management-table web-discovery-table">
          <thead><tr><th>服务</th><th>访问地址</th><th>来源</th><th>状态</th><th>暴露范围</th><th>本机上游</th><th>操作</th></tr></thead>
          <tbody>{inventory?.discovered.map((service) => <tr key={service.id}>
            <td><div className="primary-cell"><SourceIcon source={service.source} /><div><strong>{service.name}</strong><span>{service.domain ?? `TCP :${service.port}`}</span></div></div></td>
            <td>{service.exposure === 'lan' ? <a className="domain-link discovery-url" href={service.url} target="_blank" rel="noreferrer">{service.url}<ExternalLink size={13} /></a> : <span className="discovery-url mono-cell">{service.url}</span>}</td>
            <td><div className="web-source-cell"><span className="source-chip">{sourceLabels[service.source]}</span><span title={service.source_detail}>{service.source_detail}</span></div></td>
            <td><span className={service.healthy ? 'state-label healthy' : (service.status_code ? 'usage-value danger' : 'state-label neutral')}>{service.status_code ? `HTTP ${service.status_code}` : (service.healthy ? '可达' : '未响应')}</span></td>
            <td><span className={service.exposure === 'lan' ? 'usage-value warning' : 'state-label neutral'}>{service.exposure === 'lan' ? '局域网' : '仅本机'}</span></td>
            <td className="mono-cell">{service.upstream_host && service.upstream_port ? `${service.upstream_host}:${service.upstream_port}` : '-'}</td>
            <td><div className="row-tools">
              {service.exposure === 'lan' && <a className="icon-button" href={service.url} target="_blank" rel="noreferrer" title="打开服务" aria-label={`打开 ${service.name}`}><ExternalLink size={16} /></a>}
              {service.suggested_service && <button className="icon-button" onClick={() => createManagedEntry(service)} title="创建 Nginx 入口" aria-label={`为 ${service.name} 创建入口`}><Plus size={16} /></button>}
              {service.managed && <span className="state-label healthy">已托管</span>}
              {!service.managed && service.source === 'nginx' && <span className="protected-label">外部配置</span>}
            </div></td>
          </tr>)}</tbody>
        </table>
        {!inventory?.discovered.length && <div className="empty-state compact">{loading ? <LoaderCircle className="spin" size={22} /> : <Network size={22} />}<strong>{loading ? '正在扫描 Web 服务' : '未发现运行中的 Web 服务'}</strong></div>}
      </div>}

      {mode === 'managed' && <div className="table-scroll management-table-wrap">
        <table className="management-table web-services-table">
          <thead><tr><th>入口</th><th>域名</th><th>本机上游</th><th>上游状态</th><th>WebSocket</th><th>启用</th><th>操作</th></tr></thead>
          <tbody>{inventory?.items.map((service) => <tr key={service.id}>
            <td><div className="primary-cell"><AppWindow size={17} /><div><strong>{service.name}</strong><span>{service.id}</span></div></div></td>
            <td><a className="domain-link" href={`http://${service.domain}`} target="_blank" rel="noreferrer">{service.domain}<ExternalLink size={13} /></a></td>
            <td className="mono-cell">{service.upstream_host}:{service.upstream_port}</td>
            <td><span className={`state-label ${service.upstream_healthy ? 'healthy' : 'neutral'}`}>{service.upstream_healthy ? '可达' : '不可达'}</span></td>
            <td>{service.websocket ? '开启' : '关闭'}</td>
            <td><label className="switch-control compact-switch"><input type="checkbox" checked={service.enabled} onChange={() => setPending({ service, action: service.enabled ? 'disable' : 'enable' })} /><span className="switch-track" aria-hidden="true"><span /></span></label></td>
            <td><div className="row-tools">
              <button className="icon-button" onClick={() => openLogs(service)} title="查看 Nginx 日志" aria-label={`${service.name} 日志`}><FileText size={16} /></button>
              <button className="icon-button" onClick={() => { setEditor({ ...service }); setOriginalId(service.id) }} title="编辑" aria-label={`编辑 ${service.name}`}><Pencil size={16} /></button>
              <button className="icon-button" onClick={() => setPending({ service, action: 'reload' })} title="重载配置" aria-label={`重载 ${service.name}`}><RotateCw size={16} /></button>
              <button className="icon-button danger-icon" onClick={() => setPending({ service, action: 'delete' })} title="删除" aria-label={`删除 ${service.name}`}><Trash2 size={16} /></button>
            </div></td>
          </tr>)}</tbody>
        </table>
        {!inventory?.items.length && <div className="empty-state compact">{loading ? <LoaderCircle className="spin" size={22} /> : <AppWindow size={22} />}<strong>{loading ? '正在读取 Web 服务' : '暂无托管的 Web 入口'}</strong></div>}
      </div>}

      {editor && <div className="modal-backdrop" role="presentation" onMouseDown={() => !busy && setEditor(null)}><form className="service-editor" onSubmit={(event) => void saveService(event)} onMouseDown={(event) => event.stopPropagation()}>
        <div className="editor-heading"><div><AppWindow size={20} /><div><strong>{originalId ? '编辑 Web 入口' : '新增 Web 入口'}</strong><span>Nginx 反向代理</span></div></div><button type="button" className="icon-button" onClick={() => setEditor(null)} disabled={busy} title="关闭" aria-label="关闭"><X size={17} /></button></div>
        <div className="form-grid">
          <label><span>标识</span><input required pattern="[a-z0-9][a-z0-9-]{0,62}" value={editor.id} disabled={Boolean(originalId)} onChange={(event) => setEditor({ ...editor, id: event.target.value })} /></label>
          <label><span>名称</span><input required maxLength={100} value={editor.name} onChange={(event) => setEditor({ ...editor, name: event.target.value })} /></label>
          <label className="wide-field"><span>域名</span><input required value={editor.domain} onChange={(event) => setEditor({ ...editor, domain: event.target.value })} /></label>
          <label><span>上游主机</span><select value={editor.upstream_host} onChange={(event) => setEditor({ ...editor, upstream_host: event.target.value as WebService['upstream_host'] })}><option value="127.0.0.1">127.0.0.1</option><option value="localhost">localhost</option></select></label>
          <label><span>上游端口</span><input required type="number" min={1} max={65535} value={editor.upstream_port} onChange={(event) => setEditor({ ...editor, upstream_port: Number(event.target.value) })} /></label>
        </div>
        <div className="form-toggles"><label className="switch-control"><input type="checkbox" checked={editor.websocket} onChange={(event) => setEditor({ ...editor, websocket: event.target.checked })} /><span className="switch-track" aria-hidden="true"><span /></span>WebSocket</label><label className="switch-control"><input type="checkbox" checked={editor.enabled} onChange={(event) => setEditor({ ...editor, enabled: event.target.checked })} /><span className="switch-track" aria-hidden="true"><span /></span>立即启用</label></div>
        <div className="editor-actions"><button type="button" className="secondary-button" onClick={() => setEditor(null)} disabled={busy}>取消</button><button className="primary-button" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}保存并校验</button></div>
      </form></div>}

      {pending && <OperationDialog title={`确认${webActionLabels[pending.action]}`} target={`${pending.service.name} / ${pending.service.domain}`} description={pending.action === 'delete' ? '配置会备份后删除，并在 Nginx 校验通过后重载。' : '操作会先执行 Nginx 配置校验，失败时保持原配置。'} confirmLabel={webActionLabels[pending.action]} tone={pending.action === 'delete' || pending.action === 'disable' ? 'danger' : 'default'} busy={busy} onClose={() => setPending(null)} onConfirm={() => void confirmAction()} />}

      {logTarget && <div className="modal-backdrop" role="presentation" onMouseDown={() => setLogTarget(null)}><section className="web-log-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><div className="log-console-header"><div><FileText size={16} /><strong>{logTarget.name}</strong></div><div className="row-tools"><select className="inline-select" value={logStream} onChange={(event) => { const stream = event.target.value as 'access' | 'error'; setLogStream(stream); void loadLogs(logTarget, stream) }}><option value="access">访问日志</option><option value="error">错误日志</option></select><button className="icon-button dark" onClick={() => void loadLogs(logTarget, logStream)} title="刷新日志" aria-label="刷新日志"><RefreshCw className={logLoading ? 'spin' : ''} size={16} /></button><button className="icon-button dark" onClick={() => setLogTarget(null)} title="关闭" aria-label="关闭"><X size={16} /></button></div></div><pre>{logContent || (logLoading ? '正在读取日志' : '暂无日志')}</pre></section></div>}
    </section>
  )
}
