import { useCallback, useEffect, useState } from 'react'
import {
  FolderOpen,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  RotateCw,
  Save,
  Share2,
  Trash2,
  TriangleAlert,
  X,
} from 'lucide-react'
import { api, ApiError } from '../api'
import type { Share, ShareInventory } from '../types'
import { OperationDialog } from './OperationDialog'

interface SharesViewProps {
  csrfToken: string
  onError: (message: string, unauthorized?: boolean) => void
  onSuccess: (message: string) => void
}

interface PendingShareAction {
  share: Share
  action: 'enable' | 'disable' | 'delete' | 'reload'
}

const emptyShare: Share = {
  id: '',
  comment: '',
  path: '/data/',
  read_only: false,
  browseable: true,
  guest_ok: false,
  valid_users: [],
  enabled: true,
}

const shareActionLabels = {
  enable: '启用共享',
  disable: '停用共享',
  delete: '删除共享',
  reload: '重载配置',
}

export function SharesView({ csrfToken, onError, onSuccess }: SharesViewProps) {
  const [inventory, setInventory] = useState<ShareInventory | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [editor, setEditor] = useState<Share | null>(null)
  const [originalId, setOriginalId] = useState<string | null>(null)
  const [usersText, setUsersText] = useState('')
  const [pending, setPending] = useState<PendingShareAction | null>(null)

  const loadInventory = useCallback(async () => {
    setLoading(true)
    try {
      setInventory(await api.shares())
    } catch (error) {
      onError(
        error instanceof Error ? error.message : '共享列表读取失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setLoading(false)
    }
  }, [onError])

  useEffect(() => {
    void loadInventory()
  }, [loadInventory])

  function openEditor(share: Share, id: string | null) {
    setEditor({ ...share })
    setUsersText(share.valid_users.join(' '))
    setOriginalId(id)
  }

  async function saveShare(event: React.FormEvent) {
    event.preventDefault()
    if (!editor) return
    const validUsers = usersText.split(/[\s,;]+/).map((item) => item.trim()).filter(Boolean)
    setBusy(true)
    try {
      const result = await api.saveShare(csrfToken, { ...editor, valid_users: validUsers })
      onSuccess(result.message)
      setEditor(null)
      setOriginalId(null)
      await loadInventory()
    } catch (error) {
      onError(
        error instanceof Error ? error.message : '共享保存失败',
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
      const result = await api.shareAction(csrfToken, pending.share.id, pending.action)
      onSuccess(result.message)
      setPending(null)
      await loadInventory()
    } catch (error) {
      onError(
        error instanceof Error ? error.message : '共享操作失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setBusy(false)
    }
  }

  const sambaMissing = inventory && !inventory.samba_available

  return (
    <section className="management-view web-services-view">
      <div className="view-toolbar management-toolbar">
        <div className={`nginx-state ${inventory?.smbd_active ? 'healthy' : 'offline'}`}><span className="status-dot" /><div><strong>Samba</strong><span>{inventory?.smbd_active ? '运行中' : '未运行'}</span></div></div>
        <div className="toolbar-spacer" />
        <button className="primary-button" onClick={() => openEditor({ ...emptyShare }, null)} disabled={Boolean(sambaMissing)}><Plus size={16} />新增共享</button>
        <button className="icon-button" onClick={() => void loadInventory()} disabled={loading} title="刷新共享列表" aria-label="刷新共享列表"><RefreshCw className={loading ? 'spin' : ''} size={17} /></button>
      </div>

      {inventory?.warnings.length ? <div className="web-discovery-warning" role="status"><TriangleAlert size={16} /><span>{inventory.warnings.join('；')}</span></div> : null}
      {sambaMissing && <div className="web-discovery-warning" role="status"><TriangleAlert size={16} /><span>未检测到 Samba。请先通过软件管理安装 samba 软件包。</span></div>}

      <div className="table-scroll management-table-wrap">
        <table className="management-table web-services-table">
          <thead><tr><th>共享</th><th>目录</th><th>权限</th><th>可浏览</th><th>访客</th><th>授权用户</th><th>启用</th><th>操作</th></tr></thead>
          <tbody>{inventory?.items.map((share) => <tr key={share.id}>
            <td><div className="primary-cell"><Share2 size={17} /><div><strong>{share.comment}</strong><span>{share.id}</span></div></div></td>
            <td className="mono-cell">{share.path}</td>
            <td><span className={share.read_only ? 'state-label neutral' : 'usage-value warning'}>{share.read_only ? '只读' : '可写'}</span></td>
            <td>{share.browseable ? '是' : '否'}</td>
            <td>{share.guest_ok ? <span className="usage-value warning">允许</span> : '禁止'}</td>
            <td className="mono-cell">{share.valid_users.length ? share.valid_users.join(' ') : '全部用户'}</td>
            <td><label className="switch-control compact-switch"><input type="checkbox" checked={share.enabled} onChange={() => setPending({ share, action: share.enabled ? 'disable' : 'enable' })} /><span className="switch-track" aria-hidden="true"><span /></span></label></td>
            <td><div className="row-tools">
              <button className="icon-button" onClick={() => openEditor({ ...share }, share.id)} title="编辑" aria-label={`编辑 ${share.comment}`}><Pencil size={16} /></button>
              <button className="icon-button" onClick={() => setPending({ share, action: 'reload' })} title="重载 Samba 配置" aria-label={`重载 ${share.comment}`}><RotateCw size={16} /></button>
              <button className="icon-button danger-icon" onClick={() => setPending({ share, action: 'delete' })} title="删除" aria-label={`删除 ${share.comment}`}><Trash2 size={16} /></button>
            </div></td>
          </tr>)}</tbody>
        </table>
        {!inventory?.items.length && <div className="empty-state compact">{loading ? <LoaderCircle className="spin" size={22} /> : <Share2 size={22} />}<strong>{loading ? '正在读取共享列表' : '暂无托管的目录共享'}</strong></div>}
      </div>

      {inventory?.discovered.length ? <div className="resource-section">
        <div className="section-heading secondary-heading"><FolderOpen size={18} /><div><strong>外部共享</strong><span>来自 smb.conf / Samba registry 的现有配置，面板只读</span></div></div>
        <div className="table-scroll"><table className="management-table"><thead><tr><th>名称</th><th>目录</th><th>说明</th><th>权限</th><th>管理</th></tr></thead><tbody>
          {inventory.discovered.map((share) => <tr key={share.name}>
            <td><strong>{share.name}</strong></td>
            <td className="mono-cell">{share.path}</td>
            <td>{share.comment ?? '—'}</td>
            <td>{share.read_only == null ? '—' : share.read_only ? '只读' : '可写'}</td>
            <td><span className="protected-label">外部配置</span></td>
          </tr>)}
        </tbody></table></div>
      </div> : null}

      {editor && <div className="modal-backdrop" role="presentation" onMouseDown={() => !busy && setEditor(null)}><form className="service-editor" onSubmit={(event) => void saveShare(event)} onMouseDown={(event) => event.stopPropagation()}>
        <div className="editor-heading"><div><Share2 size={20} /><div><strong>{originalId ? '编辑目录共享' : '新增目录共享'}</strong><span>Samba 共享，保存时先校验再重载</span></div></div><button type="button" className="icon-button" onClick={() => setEditor(null)} disabled={busy} title="关闭" aria-label="关闭"><X size={17} /></button></div>
        <div className="form-grid">
          <label><span>标识</span><input required pattern="[a-z0-9][a-z0-9-]{0,31}" value={editor.id} disabled={Boolean(originalId)} onChange={(event) => setEditor({ ...editor, id: event.target.value })} /></label>
          <label><span>名称</span><input required maxLength={100} value={editor.comment} onChange={(event) => setEditor({ ...editor, comment: event.target.value })} /></label>
          <label className="wide-field"><span>目录路径（仅限 {(inventory?.share_roots ?? []).join('、')} 之下）</span><input required pattern="/[A-Za-z0-9._+/@:-]*" value={editor.path} onChange={(event) => setEditor({ ...editor, path: event.target.value })} /></label>
          <label className="wide-field"><span>授权用户（空格分隔，留空允许全部 Samba 用户）</span><input value={usersText} onChange={(event) => setUsersText(event.target.value)} /></label>
        </div>
        <div className="form-toggles">
          <label className="switch-control"><input type="checkbox" checked={!editor.read_only} onChange={(event) => setEditor({ ...editor, read_only: !event.target.checked })} /><span className="switch-track" aria-hidden="true"><span /></span>可写</label>
          <label className="switch-control"><input type="checkbox" checked={editor.browseable} onChange={(event) => setEditor({ ...editor, browseable: event.target.checked })} /><span className="switch-track" aria-hidden="true"><span /></span>可浏览</label>
          <label className="switch-control"><input type="checkbox" checked={editor.guest_ok} onChange={(event) => setEditor({ ...editor, guest_ok: event.target.checked })} /><span className="switch-track" aria-hidden="true"><span /></span>允许访客</label>
          <label className="switch-control"><input type="checkbox" checked={editor.enabled} onChange={(event) => setEditor({ ...editor, enabled: event.target.checked })} /><span className="switch-track" aria-hidden="true"><span /></span>立即启用</label>
        </div>
        <div className="editor-actions"><button type="button" className="secondary-button" onClick={() => setEditor(null)} disabled={busy}>取消</button><button className="primary-button" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}保存并校验</button></div>
      </form></div>}

      {pending && <OperationDialog title={`确认${shareActionLabels[pending.action]}`} target={`${pending.share.comment} / ${pending.share.path}`} description={pending.action === 'delete' ? '共享定义会备份后移除，目录数据不会被删除。' : '操作会先执行 testparm 校验，失败时保持原配置。'} confirmLabel={shareActionLabels[pending.action]} tone={pending.action === 'delete' || pending.action === 'disable' ? 'danger' : 'default'} busy={busy} onClose={() => setPending(null)} onConfirm={() => void confirmAction()} />}
    </section>
  )
}
