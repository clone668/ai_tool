import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowUp,
  Database,
  Disc3,
  FolderSearch,
  HardDrive,
  HardDriveDownload,
  HardDriveUpload,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  ShieldAlert,
} from 'lucide-react'
import { api, ApiError } from '../api'
import { formatBytes } from '../format'
import { OperationDialog } from './OperationDialog'
import type { StorageDetails, StoragePartition, StorageScan } from '../types'

interface StorageViewProps {
  csrfToken: string
  onError: (message: string, unauthorized?: boolean) => void
  onSuccess: (message: string) => void
}

type MountPending =
  | { kind: 'mount'; partition: StoragePartition }
  | { kind: 'umount'; partition: StoragePartition; mountPoint: string }

type StorageTab = 'filesystems' | 'disks' | 'scan'

const SCAN_ROOTS = ['/data', '/var', '/home', '/var/log', '/var/lib/docker', '/opt', '/usr', '/tmp']

function percentClass(value: number) {
  if (value >= 90) return 'danger'
  if (value >= 75) return 'warning'
  return 'healthy'
}

export function StorageView({ csrfToken, onError, onSuccess }: StorageViewProps) {
  const [details, setDetails] = useState<StorageDetails | null>(null)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<StorageTab>('filesystems')
  const [scanPath, setScanPath] = useState('/data')
  const [scan, setScan] = useState<StorageScan | null>(null)
  const [scanning, setScanning] = useState(false)
  const [pending, setPending] = useState<MountPending | null>(null)
  const [mountPointInput, setMountPointInput] = useState('')
  const [mountBusy, setMountBusy] = useState(false)

  const openMountDialog = (partition: StoragePartition) => {
    setMountPointInput(`/mnt/${partition.name}`)
    setPending({ kind: 'mount', partition })
  }

  const loadStorage = useCallback(async () => {
    setLoading(true)
    try {
      setDetails(await api.storage())
    } catch (error) {
      onError(
        error instanceof Error ? error.message : '存储信息读取失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setLoading(false)
    }
  }, [onError])

  const runScan = useCallback(async (path: string) => {
    setScanning(true)
    try {
      setScan(await api.storageScan(path))
      setScanPath(path)
    } catch (error) {
      onError(
        error instanceof Error ? error.message : '目录扫描失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setScanning(false)
    }
  }, [onError])

  const confirmMountAction = useCallback(async () => {
    if (!pending) return
    setMountBusy(true)
    try {
      const result = pending.kind === 'mount'
        ? await api.storageMount(csrfToken, pending.partition.path, mountPointInput.trim())
        : await api.storageUmount(csrfToken, pending.mountPoint)
      onSuccess(result.message)
      setPending(null)
      await loadStorage()
    } catch (error) {
      onError(
        error instanceof Error ? error.message : '挂载操作失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      setMountBusy(false)
    }
  }, [pending, csrfToken, mountPointInput, onSuccess, onError, loadStorage])

  useEffect(() => {
    void loadStorage()
  }, [loadStorage])

  useEffect(() => {
    if (tab === 'scan' && !scan && !scanning) void runScan(scanPath)
  }, [tab, scan, scanning, runScan, scanPath])

  const maxEntrySize = useMemo(
    () => Math.max(1, ...(scan?.entries.map((item) => item.size_bytes) ?? [1])),
    [scan],
  )

  if (!details) {
    return <div className="load-failure dashboard-loading"><LoaderCircle className="spin" size={28} /><strong>正在读取存储信息</strong></div>
  }

  const tabs: [StorageTab, string][] = [
    ['filesystems', '文件系统'],
    ['disks', '磁盘健康'],
    ['scan', '目录分析'],
  ]

  const rawParent = scanPath === '/' ? null : scanPath.slice(0, scanPath.lastIndexOf('/')) || '/'
  const parentPath = rawParent && SCAN_ROOTS.some(
    (root) => rawParent === root || rawParent.startsWith(`${root}/`),
  ) ? rawParent : null

  return (
    <section className="system-view">
      <div className="view-toolbar management-toolbar">
        <div className="segmented-control" role="tablist" aria-label="存储信息分类">
          {tabs.map(([value, label]) => <button key={value} role="tab" aria-selected={tab === value} className={tab === value ? 'active' : ''} onClick={() => setTab(value)}>{label}</button>)}
        </div>
        <div className="toolbar-spacer" />
        <button className="icon-button" onClick={() => void loadStorage()} disabled={loading} title="刷新存储信息" aria-label="刷新存储信息"><RefreshCw className={loading ? 'spin' : ''} size={17} /></button>
      </div>

      {tab === 'filesystems' && <div className="resource-section">
        <div className="section-heading"><HardDrive size={18} /><div><strong>文件系统</strong><span>{details.filesystems.length} 个挂载点</span></div></div>
        <div className="table-scroll"><table className="management-table"><thead><tr><th>挂载点</th><th>设备</th><th>格式</th><th>容量</th><th>已用</th><th>可用</th><th>使用率</th><th>inode</th></tr></thead><tbody>
          {details.filesystems.map((item) => <tr key={`${item.source}:${item.mountpoint}`}>
            <td><strong>{item.mountpoint}</strong></td>
            <td className="mono-cell">{item.source}</td>
            <td>{item.fstype}</td>
            <td>{formatBytes(item.size)}</td>
            <td>{formatBytes(item.used)}</td>
            <td>{formatBytes(item.available)}</td>
            <td><span className={`usage-value ${percentClass(item.percent)}`}>{item.percent.toFixed(1)}%</span></td>
            <td><span className={`usage-value ${percentClass(item.inodes_percent ?? 0)}`}>{item.inodes_percent?.toFixed(1) ?? '—'}%</span></td>
          </tr>)}
        </tbody></table></div>
        <div className="section-heading secondary-heading"><Database size={18} /><div><strong>交换空间</strong><span>{details.swap.length} 个交换设备</span></div></div>
        {details.swap.length ? (
          <div className="table-scroll"><table className="management-table"><thead><tr><th>设备</th><th>类型</th><th>容量</th><th>已用</th><th>使用率</th><th>优先级</th></tr></thead><tbody>
            {details.swap.map((item) => <tr key={item.name}>
              <td className="mono-cell">{item.name}</td>
              <td>{item.type}</td>
              <td>{formatBytes(item.size)}</td>
              <td>{formatBytes(item.used)}</td>
              <td><span className={`usage-value ${percentClass(item.size ? (100 * item.used) / item.size : 0)}`}>{item.size ? ((100 * item.used) / item.size).toFixed(1) : '0.0'}%</span></td>
              <td>{item.priority}</td>
            </tr>)}
          </tbody></table></div>
        ) : <div className="empty-inline">未配置交换空间</div>}
      </div>}

      {tab === 'disks' && <div className="resource-section">
        <div className="section-heading"><Disc3 size={18} /><div><strong>物理磁盘</strong><span>{details.smart_available ? 'SMART 数据可用' : '未安装 smartmontools，仅显示基础信息'}</span></div></div>
        {details.disks.length ? (
          <div className="table-scroll"><table className="management-table"><thead><tr><th>设备</th><th>型号</th><th>序列号</th><th>类型</th><th>接口</th><th>容量</th><th>温度</th><th>通电时间</th><th>SMART</th></tr></thead><tbody>
            {details.disks.map((disk) => <tr key={disk.path}>
              <td className="mono-cell"><strong>{disk.path}</strong></td>
              <td>{disk.model ?? '—'}</td>
              <td className="mono-cell">{disk.serial ?? '—'}</td>
              <td>{disk.rota == null ? '—' : disk.rota ? 'HDD' : 'SSD'}</td>
              <td>{disk.tran ?? '—'}</td>
              <td>{formatBytes(disk.size)}</td>
              <td>{disk.smart.temperature_celsius != null ? `${disk.smart.temperature_celsius.toFixed(0)} °C` : '—'}</td>
              <td>{disk.smart.power_on_hours != null ? `${disk.smart.power_on_hours.toLocaleString()} 小时` : '—'}</td>
              <td>{!disk.smart.available ? <span className="usage-value">不可用</span> : disk.smart.passed === false ? (
                <span className="usage-value danger"><ShieldAlert size={14} /> 异常</span>
              ) : disk.smart.passed ? (
                <span className="usage-value healthy"><ShieldCheck size={14} /> 正常</span>
              ) : <span className="usage-value">未知</span>}</td>
            </tr>)}
          </tbody></table></div>
        ) : <div className="empty-inline">未检测到物理磁盘</div>}
        <div className="section-heading secondary-heading"><HardDriveDownload size={18} /><div><strong>分区与挂载</strong><span>挂载点仅允许 /mnt 或 /media 下的目录</span></div></div>
        {details.partitions.length ? (
          <div className="table-scroll"><table className="management-table"><thead><tr><th>分区</th><th>标签</th><th>格式</th><th>容量</th><th>挂载点</th><th>操作</th></tr></thead><tbody>
            {details.partitions.map((partition) => {
              const primaryMount = partition.mountpoints[0] ?? null
              const managedMount = partition.mountpoints.find((point) => /^\/(mnt|media)\//.test(point)) ?? null
              return <tr key={partition.path}>
                <td className="mono-cell"><strong>{partition.path}</strong></td>
                <td>{partition.label ?? '—'}</td>
                <td>{partition.fstype}</td>
                <td>{formatBytes(partition.size)}</td>
                <td className="mono-cell">{partition.mountpoints.length ? partition.mountpoints.join(' / ') : <span className="usage-value">未挂载</span>}</td>
                <td>
                  {!primaryMount ? (
                    <button className="icon-button" onClick={() => openMountDialog(partition)} title="挂载分区" aria-label={`挂载 ${partition.path}`}><HardDriveDownload size={16} /></button>
                  ) : managedMount ? (
                    <button className="icon-button danger-icon" onClick={() => setPending({ kind: 'umount', partition, mountPoint: managedMount })} title="卸载分区" aria-label={`卸载 ${managedMount}`}><HardDriveUpload size={16} /></button>
                  ) : <span className="usage-value">系统挂载</span>}
                </td>
              </tr>
            })}
          </tbody></table></div>
        ) : <div className="empty-inline">未检测到带文件系统的分区</div>}
      </div>}

      {tab === 'scan' && <div className="resource-section">
        <div className="section-heading"><FolderSearch size={18} /><div><strong>目录占用分析</strong><span>仅扫描白名单根目录，不跨文件系统</span></div></div>
        <div className="scan-toolbar">
          {SCAN_ROOTS.map((root) => (
            <button key={root} className={`chip-button ${scanPath === root ? 'active' : ''}`} onClick={() => void runScan(root)} disabled={scanning}>{root}</button>
          ))}
        </div>
        <div className="scan-path-bar">
          {parentPath && (
            <button className="icon-button" onClick={() => void runScan(parentPath)} disabled={scanning} title="上级目录" aria-label="上级目录"><ArrowUp size={16} /></button>
          )}
          <span className="mono-cell scan-current-path">{scanPath}</span>
          {scan && <span className="scan-total">合计 {formatBytes(scan.total_bytes)}</span>}
          {scanning && <LoaderCircle className="spin" size={16} />}
        </div>
        {scan && (scan.entries.length ? (
          <div className="table-scroll"><table className="management-table"><thead><tr><th>目录</th><th>大小</th><th className="scan-share-cell">占比</th></tr></thead><tbody>
            {scan.entries.map((entry) => {
              const share = scan.total_bytes > 0 ? (100 * entry.size_bytes) / scan.total_bytes : 0
              return <tr key={entry.path} className="scan-row" onClick={() => void runScan(entry.path)}>
                <td><strong>{entry.name}</strong></td>
                <td>{formatBytes(entry.size_bytes)}</td>
                <td className="scan-share-cell">
                  <div className="scan-share">
                    <div className="scan-share-bar" style={{ width: `${Math.max(1, (100 * entry.size_bytes) / maxEntrySize)}%` }} />
                    <span>{share.toFixed(1)}%</span>
                  </div>
                </td>
              </tr>
            })}
          </tbody></table></div>
        ) : <div className="empty-inline">该目录为空或不可读</div>)}
      </div>}

      {pending?.kind === 'mount' && (
        <OperationDialog
          title="确认挂载分区"
          target={pending.partition.path}
          description="挂载不会写入 fstab，重启后如需自动挂载请另行配置。"
          confirmLabel="挂载"
          busy={mountBusy}
          onClose={() => setPending(null)}
          onConfirm={() => void confirmMountAction()}
        >
          <label className="mount-point-field">
            <span>挂载点（/mnt 或 /media 下的空目录）</span>
            <input
              value={mountPointInput}
              onChange={(event) => setMountPointInput(event.target.value)}
              pattern="/(mnt|media)/[A-Za-z0-9._-]{1,64}"
              required
            />
          </label>
        </OperationDialog>
      )}
      {pending?.kind === 'umount' && (
        <OperationDialog
          title="确认卸载分区"
          target={`${pending.partition.path} / ${pending.mountPoint}`}
          description="卸载后该目录下的数据将不可访问，请确认没有程序正在使用。"
          confirmLabel="卸载"
          tone="danger"
          busy={mountBusy}
          onClose={() => setPending(null)}
          onConfirm={() => void confirmMountAction()}
        />
      )}
    </section>
  )
}
