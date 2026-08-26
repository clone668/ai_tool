import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  Box,
  Cpu,
  Database,
  HardDrive,
  LoaderCircle,
  MemoryStick,
  Network,
  RefreshCw,
  Thermometer,
} from 'lucide-react'
import { api, ApiError } from '../api'
import { formatBytes, formatUptime } from '../format'
import type { MetricPoint, SystemDetails } from '../types'

interface SystemViewProps {
  onError: (message: string, unauthorized?: boolean) => void
}

type SystemTab = 'storage' | 'processes' | 'containers' | 'network' | 'hardware'

function chartPoints(items: MetricPoint[], field: 'cpu_percent' | 'memory_percent') {
  if (!items.length) return ''
  if (items.length === 1) {
    const y = 116 - Math.max(0, Math.min(100, items[0][field])) * 1.08
    return `0,${y.toFixed(1)} 600,${y.toFixed(1)}`
  }
  return items.map((item, index) => {
    const x = index * 600 / (items.length - 1)
    const y = 116 - Math.max(0, Math.min(100, item[field])) * 1.08
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

function percentClass(value: number) {
  if (value >= 90) return 'danger'
  if (value >= 75) return 'warning'
  return 'healthy'
}

export function SystemView({ onError }: SystemViewProps) {
  const [details, setDetails] = useState<SystemDetails | null>(null)
  const [loading, setLoading] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [tab, setTab] = useState<SystemTab>('storage')

  const loadSystem = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      setDetails(await api.system())
    } catch (error) {
      onError(
        error instanceof Error ? error.message : '系统信息读取失败',
        error instanceof ApiError && error.status === 401,
      )
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [onError])

  useEffect(() => {
    void loadSystem()
  }, [loadSystem])

  useEffect(() => {
    if (!autoRefresh) return
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void loadSystem(true)
    }, 10_000)
    return () => window.clearInterval(timer)
  }, [autoRefresh, loadSystem])

  const dataDisk = useMemo(() => details?.filesystems.find((item) => item.mountpoint === '/data')
    ?? details?.filesystems[0], [details])

  if (!details) {
    return <div className="load-failure dashboard-loading"><LoaderCircle className="spin" size={28} /><strong>正在采集系统指标</strong></div>
  }

  const tabs: [SystemTab, string][] = [
    ['storage', '磁盘'],
    ['processes', '进程'],
    ['containers', '容器'],
    ['network', '网络'],
    ['hardware', '硬件'],
  ]

  return (
    <section className="system-view">
      <div className="view-toolbar management-toolbar">
        <div className="segmented-control" role="tablist" aria-label="系统信息分类">
          {tabs.map(([value, label]) => <button key={value} role="tab" aria-selected={tab === value} className={tab === value ? 'active' : ''} onClick={() => setTab(value)}>{label}</button>)}
        </div>
        <div className="toolbar-spacer" />
        <label className="switch-control">
          <input type="checkbox" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />
          <span className="switch-track" aria-hidden="true"><span /></span>
          自动刷新
        </label>
        <button className="icon-button" onClick={() => void loadSystem()} disabled={loading} title="刷新系统信息" aria-label="刷新系统信息"><RefreshCw className={loading ? 'spin' : ''} size={17} /></button>
      </div>

      <div className="system-metrics">
        <div><span className="metric-icon cpu"><Cpu size={18} /></span><div><small>CPU</small><strong>{details.cpu.percent.toFixed(1)}%</strong><span>{details.cpu.load_average.join(' / ')}</span></div></div>
        <div><span className="metric-icon memory"><MemoryStick size={18} /></span><div><small>内存</small><strong>{details.memory.percent.toFixed(1)}%</strong><span>{formatBytes(details.memory.used)} / {formatBytes(details.memory.total)}</span></div></div>
        <div><span className="metric-icon disk"><HardDrive size={18} /></span><div><small>/data</small><strong>{(dataDisk?.percent ?? 0).toFixed(1)}%</strong><span>{formatBytes(dataDisk?.used)} / {formatBytes(dataDisk?.size)}</span></div></div>
        <div><span className="metric-icon service"><Activity size={18} /></span><div><small>失败服务</small><strong>{details.failed_units}</strong><span>运行 {formatUptime(details.uptime_seconds)}</span></div></div>
      </div>

      <div className="history-band">
        <div className="history-heading"><div><strong>资源趋势</strong><span>最近 {details.history.length} 次采样</span></div><div className="chart-legend"><span className="cpu-line">CPU</span><span className="memory-line">内存</span></div></div>
        <div className="resource-chart" aria-label="CPU 与内存使用率趋势图">
          <span className="chart-label top">100%</span><span className="chart-label bottom">0%</span>
          <svg viewBox="0 0 600 120" preserveAspectRatio="none" role="img">
            <line x1="0" y1="60" x2="600" y2="60" className="chart-grid" />
            <polyline points={chartPoints(details.history, 'cpu_percent')} className="chart-line cpu" />
            <polyline points={chartPoints(details.history, 'memory_percent')} className="chart-line memory" />
          </svg>
        </div>
      </div>

      {tab === 'storage' && <div className="resource-section">
        <div className="section-heading"><HardDrive size={18} /><div><strong>文件系统</strong><span>{details.filesystems.length} 个挂载点</span></div></div>
        <div className="table-scroll"><table className="management-table"><thead><tr><th>挂载点</th><th>设备</th><th>格式</th><th>容量</th><th>已用</th><th>可用</th><th>使用率</th><th>inode</th></tr></thead><tbody>{details.filesystems.map((item) => <tr key={`${item.source}:${item.mountpoint}`}><td><strong>{item.mountpoint}</strong></td><td className="mono-cell">{item.source}</td><td>{item.fstype}</td><td>{formatBytes(item.size)}</td><td>{formatBytes(item.used)}</td><td>{formatBytes(item.available)}</td><td><span className={`usage-value ${percentClass(item.percent)}`}>{item.percent.toFixed(1)}%</span></td><td><span className={`usage-value ${percentClass(item.inodes_percent ?? 0)}`}>{item.inodes_percent?.toFixed(1) ?? '—'}%</span></td></tr>)}</tbody></table></div>
        <div className="section-heading secondary-heading"><Database size={18} /><div><strong>块设备</strong><span>{details.block_devices.length} 个顶层设备</span></div></div>
        <div className="table-scroll"><table className="management-table"><thead><tr><th>设备</th><th>类型</th><th>型号</th><th>传输</th><th>容量</th><th>文件系统</th></tr></thead><tbody>{details.block_devices.map((device, index) => <tr key={String(device.path ?? device.name ?? index)}><td className="mono-cell">{String(device.path ?? device.name ?? '—')}</td><td>{String(device.type ?? '—')}</td><td>{String(device.model ?? '—')}</td><td>{String(device.tran ?? '—')}</td><td>{formatBytes(Number(device.size ?? 0))}</td><td>{String(device.fstype ?? '—')}</td></tr>)}</tbody></table></div>
      </div>}

      {tab === 'processes' && <div className="resource-section"><div className="section-heading"><Activity size={18} /><div><strong>高占用进程</strong><span>按 CPU 使用率排序</span></div></div><div className="table-scroll"><table className="management-table"><thead><tr><th>PID</th><th>进程</th><th>用户</th><th>CPU</th><th>内存</th><th>RSS</th><th>状态</th></tr></thead><tbody>{details.processes.map((item) => <tr key={item.pid}><td className="mono-cell">{item.pid}</td><td><strong>{item.command}</strong></td><td>{item.user}</td><td>{item.cpu_percent.toFixed(1)}%</td><td>{item.memory_percent.toFixed(1)}%</td><td>{formatBytes(item.rss_bytes)}</td><td>{item.state}</td></tr>)}</tbody></table></div></div>}

      {tab === 'containers' && <div className="resource-section"><div className="section-heading"><Box size={18} /><div><strong>容器资源</strong><span>{details.containers.length} 个运行容器</span></div></div><div className="table-scroll"><table className="management-table"><thead><tr><th>容器</th><th>CPU</th><th>内存</th><th>内存率</th><th>网络 I/O</th><th>块 I/O</th><th>进程数</th></tr></thead><tbody>{details.containers.map((item) => <tr key={item.name}><td><strong>{item.name}</strong></td><td>{item.cpu}</td><td>{item.memory}</td><td>{item.memory_percent}</td><td>{item.network}</td><td>{item.block_io}</td><td>{item.pids}</td></tr>)}</tbody></table></div></div>}

      {tab === 'network' && <div className="resource-section"><div className="section-heading"><Network size={18} /><div><strong>网络接口</strong><span>自开机累计流量</span></div></div><div className="table-scroll"><table className="management-table"><thead><tr><th>接口</th><th>接收</th><th>接收包</th><th>接收错误</th><th>发送</th><th>发送包</th><th>发送错误</th></tr></thead><tbody>{details.network.map((item) => <tr key={item.interface}><td><strong>{item.interface}</strong></td><td>{formatBytes(item.received_bytes)}</td><td>{item.received_packets.toLocaleString()}</td><td>{item.received_errors}</td><td>{formatBytes(item.sent_bytes)}</td><td>{item.sent_packets.toLocaleString()}</td><td>{item.sent_errors}</td></tr>)}</tbody></table></div></div>}

      {tab === 'hardware' && <div className="hardware-layout">
        <div className="fact-panel"><div className="section-heading"><Cpu size={18} /><div><strong>处理器</strong><span>{details.cpu.cores} 逻辑核心</span></div></div><dl><dt>型号</dt><dd>{details.cpu.model}</dd><dt>1 / 5 / 15 分钟负载</dt><dd>{details.cpu.load_average.join(' / ')}</dd><dt>SMART 工具</dt><dd>{details.smart_available ? '可用' : '未安装'}</dd></dl></div>
        <div className="fact-panel"><div className="section-heading"><Thermometer size={18} /><div><strong>温度</strong><span>{details.cpu.temperatures.length} 个传感器</span></div></div>{details.cpu.temperatures.length ? <dl>{details.cpu.temperatures.map((item) => <span className="temperature-row" key={item.label}><dt>{item.label}</dt><dd>{item.celsius.toFixed(1)} °C</dd></span>)}</dl> : <div className="empty-inline">未读取到温度传感器</div>}</div>
      </div>}
    </section>
  )
}
