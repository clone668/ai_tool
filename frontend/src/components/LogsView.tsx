import { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, LoaderCircle, RefreshCw, ScrollText } from 'lucide-react'
import { api } from '../api'
import { formatDate } from '../format'
import type { Component, Project } from '../types'

interface LogSelection {
  projectId: string
  componentId: string
}

interface LogsViewProps {
  projects: Project[]
  initialSelection: LogSelection | null
  onError: (message: string, unauthorized?: boolean) => void
}

export function LogsView({ projects, initialSelection, onError }: LogsViewProps) {
  const loggableProjects = useMemo(
    () => projects.filter((project) => project.components.length > 0),
    [projects],
  )
  const fallbackProject = loggableProjects[0]
  const [projectId, setProjectId] = useState(initialSelection?.projectId ?? fallbackProject?.id ?? '')
  const selectedProject = loggableProjects.find((project) => project.id === projectId) ?? fallbackProject
  const initialComponent = initialSelection && initialSelection.projectId === selectedProject?.id
    ? initialSelection.componentId
    : selectedProject?.components[0]?.id ?? ''
  const [componentId, setComponentId] = useState(initialComponent)
  const [lines, setLines] = useState(200)
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)

  const selectedComponent = selectedProject?.components.find((item) => item.id === componentId)
    ?? selectedProject?.components[0]

  const loadLogs = useCallback(async (quiet = false) => {
    if (!selectedProject || !selectedComponent) return
    if (!quiet) setLoading(true)
    try {
      const result = await api.logs(selectedProject.id, selectedComponent.id, lines)
      setContent(result.content)
      setUpdatedAt(new Date().toISOString())
    } catch (error) {
      const message = error instanceof Error ? error.message : '日志读取失败'
      const unauthorized = error instanceof Error && 'status' in error && error.status === 401
      onError(message, unauthorized)
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [lines, onError, selectedComponent, selectedProject])

  useEffect(() => {
    void loadLogs()
  }, [loadLogs])

  useEffect(() => {
    if (!autoRefresh) return
    const timer = window.setInterval(() => void loadLogs(true), 10_000)
    return () => window.clearInterval(timer)
  }, [autoRefresh, loadLogs])

  function changeProject(value: string) {
    const project = loggableProjects.find((item) => item.id === value)
    setProjectId(value)
    setComponentId(project?.components[0]?.id ?? '')
  }

  function downloadLogs() {
    if (!selectedProject || !selectedComponent) return
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${selectedProject.id}-${selectedComponent.id}.log`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section className="logs-view">
      <div className="view-toolbar logs-toolbar">
        <div className="field-group">
          <label htmlFor="log-project">项目</label>
          <select id="log-project" value={selectedProject?.id ?? ''} onChange={(event) => changeProject(event.target.value)}>
            {loggableProjects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </div>
        <div className="field-group">
          <label htmlFor="log-component">组件</label>
          <select id="log-component" value={selectedComponent?.id ?? ''} onChange={(event) => setComponentId(event.target.value)}>
            {selectedProject?.components.map((component: Component) => (
              <option key={component.id} value={component.id}>{component.label}</option>
            ))}
          </select>
        </div>
        <div className="field-group compact-field">
          <label htmlFor="log-lines">行数</label>
          <select id="log-lines" value={lines} onChange={(event) => setLines(Number(event.target.value))}>
            {[100, 200, 500, 1000].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </div>
        <label className="switch-control">
          <input type="checkbox" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />
          <span className="switch-track" aria-hidden="true"><span /></span>
          自动刷新
        </label>
        <div className="toolbar-spacer" />
        <button className="icon-button" onClick={downloadLogs} disabled={!content} title="下载日志" aria-label="下载日志">
          <Download size={17} />
        </button>
        <button className="icon-button" onClick={() => void loadLogs()} disabled={loading} title="刷新日志" aria-label="刷新日志">
          <RefreshCw className={loading ? 'spin' : ''} size={17} />
        </button>
      </div>

      <div className="log-console">
        <div className="log-console-header">
          <div>
            <ScrollText size={16} />
            <strong>{selectedComponent?.label ?? '日志'}</strong>
          </div>
          <span>{updatedAt ? `更新于 ${formatDate(updatedAt)}` : '正在读取'}</span>
        </div>
        {loading && !content ? (
          <div className="console-loading"><LoaderCircle className="spin" size={22} />读取日志</div>
        ) : (
          <pre tabIndex={0}>{content || '暂无日志输出'}</pre>
        )}
      </div>
    </section>
  )
}
