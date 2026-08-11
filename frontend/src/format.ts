import type { ActionName, HealthStatus } from './types'

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

export function formatBytes(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let amount = value
  let unitIndex = 0
  while (amount >= 1024 && unitIndex < units.length - 1) {
    amount /= 1024
    unitIndex += 1
  }
  return `${amount >= 10 || unitIndex === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unitIndex]}`
}

export function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  if (days > 0) return `${days} 天 ${hours} 小时`
  const minutes = Math.floor((seconds % 3600) / 60)
  return `${hours} 小时 ${minutes} 分钟`
}

export function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : dateFormatter.format(date)
}

export const statusLabels: Record<HealthStatus, string> = {
  healthy: '正常',
  degraded: '需关注',
  offline: '离线',
}

export const actionLabels: Record<ActionName, string> = {
  start: '启动',
  restart: '重启',
  stop: '停止',
}
