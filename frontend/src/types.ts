export type HealthStatus = 'healthy' | 'degraded' | 'offline'
export type ActionName = 'start' | 'restart' | 'stop'
export type ProjectKind = 'application' | 'infrastructure' | 'scheduled'

export interface SessionInfo {
  username: string
  csrf_token: string
  expires_at: string
  terminal_enabled: boolean
}

export interface ContainerState {
  name: string
  state: string
  health: string | null
  healthy: boolean
  started_at?: string | null
  restart_count: number
}

export interface Component {
  id: string
  label: string
  type: 'systemd' | 'user_systemd' | 'compose' | 'cron'
  service?: string
  user?: string
  compose_file?: string
  containers?: string[]
  actions: ActionName[]
  required?: boolean
  state: string
  substate: string
  healthy: boolean
  pid?: number
  memory_bytes?: number | null
  since?: string | null
  detail?: string
  children?: ContainerState[]
}

export interface HealthCheck {
  id: string
  label: string
  type: 'http' | 'tcp'
  healthy: boolean
  latency_ms: number
  detail: string
  status_code?: number | null
}

export interface Project {
  id: string
  name: string
  description: string
  kind: ProjectKind
  runtime: string
  path?: string
  url?: string
  status: HealthStatus
  components: Component[]
  checks: HealthCheck[]
}

export interface HostState {
  id: string
  name: string
  address: string
  location: string
  hostname: string
  cpu_percent: number
  load_average: number[]
  memory_total: number
  memory_used: number
  memory_percent: number
  disk_total: number
  disk_used: number
  disk_percent: number
  uptime_seconds: number
  platform: string
}

export interface DashboardSnapshot {
  generated_at: string
  host: HostState
  summary: {
    healthy: number
    degraded: number
    offline: number
    total: number
  }
  projects: Project[]
}

export interface AuditItem {
  id: number
  created_at: string
  username: string
  ip_address: string
  project_id: string | null
  component_id: string | null
  action: string
  outcome: 'success' | 'failed' | 'denied'
  detail: string
}

export type PackageManager = 'apt' | 'snap'
export type SoftwareAction = 'install' | 'upgrade' | 'remove' | 'purge' | 'refresh'

export interface SoftwareItem {
  manager: PackageManager
  name: string
  version: string | null
  architecture?: string | null
  revision?: string
  tracking?: string
  size_bytes: number | null
  installed: boolean
  description: string
  protected: boolean
}

export interface SoftwareInventory {
  query: string
  items: SoftwareItem[]
  counts: { installed: number; available: number }
  managers: { apt: boolean; snap: boolean }
}

export interface SoftwarePlan {
  manager: PackageManager
  name: string
  action: SoftwareAction
  changes: string[]
  summary: string
  confirmation_token: string
}

export type StartupScope = 'system' | 'user' | 'docker'
export type StartupAction = 'start' | 'stop' | 'restart' | 'enable' | 'disable' | 'policy'

export interface StartupItem {
  scope: StartupScope
  name: string
  enabled_state: string
  active_state: string
  substate: string
  protected: boolean
}

export interface StartupInventory {
  items: StartupItem[]
  total: number
}

export interface FilesystemState {
  source: string
  fstype: string
  mountpoint: string
  size: number
  used: number
  available: number
  percent: number
  inodes?: number
  inodes_used?: number
  inodes_percent?: number
}

export interface ProcessState {
  pid: number
  user: string
  command: string
  cpu_percent: number
  memory_percent: number
  rss_bytes: number
  state: string
}

export interface ContainerResourceState {
  name: string
  cpu: string
  memory: string
  memory_percent: string
  network: string
  block_io: string
  pids: string
}

export interface NetworkState {
  interface: string
  received_bytes: number
  received_packets: number
  received_errors: number
  sent_bytes: number
  sent_packets: number
  sent_errors: number
}

export interface MetricPoint {
  created_at: string
  cpu_percent: number
  memory_percent: number
  load_one: number
  disk_percent: number
}

export interface SystemDetails {
  generated_at: string
  cpu: {
    model: string
    cores: number
    percent: number
    load_average: number[]
    temperatures: { label: string; celsius: number }[]
  }
  memory: {
    total: number
    available: number
    used: number
    percent: number
    cached: number
    buffers: number
    swap_total: number
    swap_used: number
    swap_percent: number
  }
  filesystems: FilesystemState[]
  block_devices: Record<string, unknown>[]
  processes: ProcessState[]
  containers: ContainerResourceState[]
  network: NetworkState[]
  uptime_seconds: number
  failed_units: number
  smart_available: boolean
  history: MetricPoint[]
}

export interface SmartInfo {
  available: boolean
  passed: boolean | null
  temperature_celsius: number | null
  power_on_hours: number | null
}

export interface StorageDisk {
  name: string
  path: string
  model: string | null
  serial: string | null
  size: number
  rota: boolean | null
  tran: string | null
  smart: SmartInfo
}

export interface SwapDevice {
  name: string
  type: string
  size: number
  used: number
  priority: number
}

export interface StoragePartition {
  name: string
  path: string
  fstype: string
  label: string | null
  size: number
  mountpoints: string[]
}

export interface StorageDetails {
  generated_at: string
  filesystems: FilesystemState[]
  disks: StorageDisk[]
  partitions: StoragePartition[]
  swap: SwapDevice[]
  smart_available: boolean
}

export interface StorageScanEntry {
  path: string
  name: string
  size_bytes: number
}

export interface StorageScan {
  path: string
  total_bytes: number
  entries: StorageScanEntry[]
}

export interface Share {
  id: string
  comment: string
  path: string
  read_only: boolean
  browseable: boolean
  guest_ok: boolean
  valid_users: string[]
  enabled: boolean
}

export interface DiscoveredShare {
  name: string
  path: string
  comment: string | null
  read_only: boolean | null
  managed: boolean
}

export interface ShareInventory {
  items: Share[]
  discovered: DiscoveredShare[]
  samba_available: boolean
  smbd_active: boolean
  share_roots: string[]
  warnings: string[]
}

export type RiskLevel = 'safe' | 'medium' | 'high'

export interface CleanupCandidate {
  id: string
  label: string
  risk: RiskLevel
  size_bytes: number | null
  detail: string
  actionable?: boolean
  confirmation_token?: string
}

export interface OptimizationItem {
  id: string
  label: string
  status: 'applied' | 'recommended' | 'attention' | 'ok'
  detail: string
  reversible: boolean
  actionable?: boolean
  confirmation_action?: string
  confirmation_token?: string
}

export interface MaintenanceDetails {
  cleanup: {
    generated_at: string
    candidates: CleanupCandidate[]
    docker: Record<string, unknown>[]
  }
  optimization: {
    generated_at: string
    recommendations: OptimizationItem[]
    facts: { swappiness: number; reboot_required: boolean; updates: number }
  }
}

export interface WebService {
  id: string
  name: string
  domain: string
  upstream_host: '127.0.0.1' | 'localhost'
  upstream_port: number
  websocket: boolean
  enabled: boolean
  upstream_healthy?: boolean
}

export interface DiscoveredWebService {
  id: string
  name: string
  url: string
  domain: string | null
  port: number
  protocol: 'http' | 'https'
  source: 'nginx' | 'docker' | 'systemd' | 'project' | 'process'
  source_detail: string
  exposure: 'lan' | 'loopback'
  healthy: boolean
  status_code: number | null
  managed: boolean
  suggested_service: WebService | null
  upstream_host: string | null
  upstream_port: number | null
}

export interface WebInventory {
  items: WebService[]
  discovered: DiscoveredWebService[]
  nginx_active: boolean
  warnings: string[]
}

export interface UpdateCommitInfo {
  ref: string
  available: boolean
  commit?: string
  short?: string
  time?: string
  subject?: string
}

export interface UpdateRunState {
  running: boolean
  status?: 'running' | 'success' | 'failed'
  started_at?: string
  finished_at?: string
  from_commit?: string | null
  to_commit?: string | null
  message?: string
}

export interface UpdateStatus {
  generated_at: string
  app_dir: string
  branch: string
  upstream: string | null
  current: UpdateCommitInfo
  remote: UpdateCommitInfo
  ahead: number
  behind: number
  update_available: boolean
  running: boolean
  fetch_error: string | null
  last_run: UpdateRunState | null
  log_path: string
}
