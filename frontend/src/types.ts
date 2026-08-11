export type HealthStatus = 'healthy' | 'degraded' | 'offline'
export type ActionName = 'start' | 'restart' | 'stop'
export type ProjectKind = 'application' | 'infrastructure' | 'scheduled'

export interface SessionInfo {
  username: string
  csrf_token: string
  expires_at: string
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
