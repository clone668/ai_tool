import { FormEvent, useState } from 'react'
import { Eye, EyeOff, LoaderCircle, LockKeyhole, ServerCog } from 'lucide-react'

interface LoginViewProps {
  onLogin: (username: string, password: string) => Promise<void>
}

export function LoginView({ onLogin }: LoginViewProps) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await onLogin(username.trim(), password)
    } catch (value) {
      setError(value instanceof Error ? value.message : '登录失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-shell" aria-labelledby="login-title">
        <div className="login-identity">
          <div className="brand-mark brand-mark-large" aria-hidden="true">
            <ServerCog size={29} strokeWidth={1.8} />
          </div>
          <div>
            <h1 id="login-title">节点台</h1>
            <p>Ubuntu 项目运维控制台</p>
          </div>
          <div className="login-host">
            <span className="status-dot healthy" />
            <div>
              <strong>huxi-H81M</strong>
              <span>192.168.2.240</span>
            </div>
          </div>
        </div>

        <form className="login-form" onSubmit={submit}>
          <div className="login-form-heading">
            <LockKeyhole size={20} />
            <h2>管理员登录</h2>
          </div>
          <label htmlFor="username">用户名</label>
          <input
            id="username"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
          <label htmlFor="password">密码</label>
          <div className="password-field">
            <input
              id="password"
              name="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              autoFocus
            />
            <button
              type="button"
              className="input-icon-button"
              onClick={() => setShowPassword((value) => !value)}
              title={showPassword ? '隐藏密码' : '显示密码'}
              aria-label={showPassword ? '隐藏密码' : '显示密码'}
            >
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
          {error && <div className="form-error" role="alert">{error}</div>}
          <button className="primary-button login-button" disabled={submitting}>
            {submitting && <LoaderCircle className="spin" size={17} />}
            登录
          </button>
        </form>
      </section>
    </main>
  )
}
