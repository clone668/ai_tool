import { useEffect, useRef, useState } from 'react'
import { Eraser, PlugZap, RefreshCw, TerminalSquare } from 'lucide-react'
import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'

interface TerminalViewProps {
  enabled: boolean
}

type ConnectionState = 'connecting' | 'connected' | 'closed' | 'error'

const stateLabels: Record<ConnectionState, string> = {
  connecting: '连接中',
  connected: '已连接',
  closed: '已断开',
  error: '连接失败',
}

export function TerminalView({ enabled }: TerminalViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<Terminal | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const [connectionKey, setConnectionKey] = useState(0)
  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting')

  useEffect(() => {
    if (!enabled || !containerRef.current) return
    const terminal = new Terminal({
      cursorBlink: true,
      convertEol: true,
      fontFamily: '"Cascadia Mono", "JetBrains Mono", Consolas, monospace',
      fontSize: 13,
      lineHeight: 1.25,
      scrollback: 5000,
      theme: {
        background: '#101614',
        foreground: '#d8e2df',
        cursor: '#58b8a9',
        selectionBackground: '#35534d',
        black: '#17201e',
        red: '#e56872',
        green: '#52bc86',
        yellow: '#e1a84e',
        blue: '#6f9dd8',
        magenta: '#b58bd2',
        cyan: '#58b8a9',
        white: '#d8e2df',
      },
    })
    const fitAddon = new FitAddon()
    terminal.loadAddon(fitAddon)
    terminal.open(containerRef.current)
    terminalRef.current = terminal
    fitAddon.fit()

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${window.location.host}/api/terminal/ws`)
    socketRef.current = socket
    setConnectionState('connecting')

    const sendResize = () => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'resize', rows: terminal.rows, cols: terminal.cols }))
      }
    }
    socket.onopen = () => {
      setConnectionState('connected')
      sendResize()
      terminal.focus()
    }
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(String(event.data)) as { type?: string; data?: string; message?: string }
        if (message.type === 'output' && message.data) terminal.write(message.data)
        if (message.type === 'error' && message.message) terminal.writeln(`\r\n${message.message}`)
      } catch {
        terminal.write(String(event.data))
      }
    }
    socket.onerror = () => setConnectionState('error')
    socket.onclose = () => setConnectionState((current) => current === 'error' ? current : 'closed')

    const input = terminal.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data }))
      }
    })
    const observer = new ResizeObserver(() => {
      fitAddon.fit()
      sendResize()
    })
    observer.observe(containerRef.current)

    return () => {
      observer.disconnect()
      input.dispose()
      socket.close()
      terminal.dispose()
      socketRef.current = null
      terminalRef.current = null
    }
  }, [connectionKey, enabled])

  if (!enabled) {
    return <div className="load-failure"><PlugZap size={28} /><strong>Web 终端未启用</strong><span>服务器配置已关闭终端入口</span></div>
  }

  return (
    <section className="terminal-view">
      <div className="terminal-toolbar">
        <div className={`terminal-state ${connectionState}`}><span className="status-dot" /><TerminalSquare size={16} /><strong>ai-tool-shell@节点台</strong><span>{stateLabels[connectionState]}</span></div>
        <div className="toolbar-spacer" />
        <button className="icon-button dark" onClick={() => terminalRef.current?.clear()} title="清屏" aria-label="清屏"><Eraser size={17} /></button>
        <button className="icon-button dark" onClick={() => setConnectionKey((value) => value + 1)} title="重新连接" aria-label="重新连接"><RefreshCw size={17} /></button>
      </div>
      <div className="terminal-surface" ref={containerRef} />
    </section>
  )
}
