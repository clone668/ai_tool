import {
  History,
  LayoutDashboard,
  LogOut,
  ScrollText,
  ServerCog,
  UserRound,
} from 'lucide-react'

export type ViewName = 'overview' | 'logs' | 'audit'

interface SidebarProps {
  activeView: ViewName
  username: string
  onView: (view: ViewName) => void
  onLogout: () => void
}

const navigation = [
  { id: 'overview' as const, label: '总览', icon: LayoutDashboard },
  { id: 'logs' as const, label: '日志', icon: ScrollText },
  { id: 'audit' as const, label: '审计', icon: History },
]

export function Sidebar({ activeView, username, onView, onLogout }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-mark" aria-hidden="true">
          <ServerCog size={22} strokeWidth={1.8} />
        </div>
        <div>
          <strong>节点台</strong>
          <span>AI Tool</span>
        </div>
      </div>

      <nav className="main-nav" aria-label="主导航">
        {navigation.map((item) => {
          const Icon = item.icon
          return (
            <button
              key={item.id}
              className={activeView === item.id ? 'active' : ''}
              onClick={() => onView(item.id)}
              aria-label={item.label}
            >
              <Icon size={18} />
              <span>{item.label}</span>
            </button>
          )
        })}
      </nav>

      <div className="sidebar-user">
        <div className="user-identity">
          <UserRound size={18} />
          <div>
            <strong>{username}</strong>
            <span>管理员</span>
          </div>
        </div>
        <button className="icon-button dark" onClick={onLogout} title="退出登录" aria-label="退出登录">
          <LogOut size={17} />
        </button>
      </div>
    </aside>
  )
}
