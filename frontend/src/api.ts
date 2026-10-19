import type {
  ActionName,
  AuditItem,
  DashboardSnapshot,
  MaintenanceDetails,
  PackageManager,
  SessionInfo,
  Share,
  ShareInventory,
  SoftwareAction,
  SoftwareInventory,
  SoftwarePlan,
  StartupAction,
  StartupInventory,
  StartupScope,
  StorageDetails,
  StorageScan,
  SystemDetails,
  WebInventory,
  WebService,
} from './types'

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  const body = await response.json().catch(() => null) as { detail?: string } | null
  if (!response.ok) {
    throw new ApiError(body?.detail ?? `请求失败 (${response.status})`, response.status)
  }
  return body as T
}

export const api = {
  session: () => request<SessionInfo>('/api/auth/session'),
  login: (username: string, password: string) =>
    request<SessionInfo>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  logout: (csrfToken: string) =>
    request<{ ok: boolean }>('/api/auth/logout', {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrfToken },
    }),
  dashboard: (force = false) =>
    request<DashboardSnapshot>(`/api/dashboard${force ? '?force=true' : ''}`),
  logs: (projectId: string, componentId: string, lines: number) =>
    request<{ content: string; lines: number }>(
      `/api/projects/${encodeURIComponent(projectId)}/components/${encodeURIComponent(componentId)}/logs?lines=${lines}`,
    ),
  action: (
    csrfToken: string,
    projectId: string,
    componentId: string,
    action: ActionName,
  ) => request<{ ok: boolean; message: string }>(
    `/api/projects/${encodeURIComponent(projectId)}/actions`,
    {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ component_id: componentId, action }),
    },
  ),
  audit: () => request<{ items: AuditItem[] }>('/api/audit?limit=150'),
  software: (query = '') => request<SoftwareInventory>(
    `/api/software?query=${encodeURIComponent(query)}&limit=300`,
  ),
  softwarePlan: (
    csrfToken: string,
    manager: PackageManager,
    name: string,
    action: SoftwareAction,
  ) => request<SoftwarePlan>('/api/software/plan', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken },
    body: JSON.stringify({ manager, name, action }),
  }),
  softwareAction: (
    csrfToken: string,
    manager: PackageManager,
    name: string,
    action: SoftwareAction,
    confirmationToken?: string,
  ) => request<{ ok: boolean; message: string }>('/api/software/actions', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken },
    body: JSON.stringify({ manager, name, action, confirmation_token: confirmationToken }),
  }),
  startup: (query = '') => request<StartupInventory>(
    `/api/startup?query=${encodeURIComponent(query)}&limit=1000`,
  ),
  startupAction: (
    csrfToken: string,
    scope: StartupScope,
    name: string,
    action: StartupAction,
    value = '_',
  ) => request<{ ok: boolean; message: string }>('/api/startup/actions', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken },
    body: JSON.stringify({ scope, name, action, value }),
  }),
  system: () => request<SystemDetails>('/api/system?history_limit=120'),
  storage: () => request<StorageDetails>('/api/storage'),
  storageScan: (path: string) => request<StorageScan>(
    `/api/storage/scan?path=${encodeURIComponent(path)}`,
  ),
  storageMount: (csrfToken: string, device: string, mountPoint: string) =>
    request<{ ok: boolean; message: string }>('/api/storage/mount', {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ device, mount_point: mountPoint }),
    }),
  storageUmount: (csrfToken: string, mountPoint: string) =>
    request<{ ok: boolean; message: string }>('/api/storage/umount', {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ mount_point: mountPoint }),
    }),
  storageFormat: (csrfToken: string, device: string, fstype: string, label: string) =>
    request<{ ok: boolean; message: string }>('/api/storage/format', {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ device, fstype, label }),
    }),
  maintenance: () => request<MaintenanceDetails>('/api/maintenance'),
  maintenanceAction: (csrfToken: string, action: string, confirmationToken: string) =>
    request<{ ok: boolean; message: string }>('/api/maintenance/actions', {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ action, confirmation_token: confirmationToken }),
    }),
  optimizationAction: (csrfToken: string, action: string, confirmationToken: string) =>
    request<{ ok: boolean; message: string }>('/api/optimization/actions', {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ action, confirmation_token: confirmationToken }),
    }),
  webServices: () => request<WebInventory>('/api/web-services'),
  shares: () => request<ShareInventory>('/api/shares'),
  saveShare: (csrfToken: string, share: Share) =>
    request<{ ok: boolean; message: string }>(
      `/api/shares/${encodeURIComponent(share.id)}`,
      {
        method: 'PUT',
        headers: { 'X-CSRF-Token': csrfToken },
        body: JSON.stringify(share),
      },
    ),
  shareAction: (csrfToken: string, shareId: string, action: string) =>
    request<{ ok: boolean; message: string }>(
      `/api/shares/${encodeURIComponent(shareId)}/actions`,
      {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrfToken },
        body: JSON.stringify({ action }),
      },
    ),
  saveWebService: (csrfToken: string, service: WebService) =>
    request<{ ok: boolean; message: string }>(
      `/api/web-services/${encodeURIComponent(service.id)}`,
      {
        method: 'PUT',
        headers: { 'X-CSRF-Token': csrfToken },
        body: JSON.stringify(service),
      },
    ),
  webServiceAction: (csrfToken: string, serviceId: string, action: string) =>
    request<{ ok: boolean; message: string }>(
      `/api/web-services/${encodeURIComponent(serviceId)}/actions`,
      {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrfToken },
        body: JSON.stringify({ action }),
      },
    ),
  webServiceLogs: (serviceId: string, stream: 'access' | 'error', lines = 200) =>
    request<{ content: string; stream: string; lines: number }>(
      `/api/web-services/${encodeURIComponent(serviceId)}/logs?stream=${stream}&lines=${lines}`,
    ),
}
