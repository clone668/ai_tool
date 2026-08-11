import type { ActionName, AuditItem, DashboardSnapshot, SessionInfo } from './types'

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
}
