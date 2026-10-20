import {
  AppWindow,
  ArrowUpCircle,
  Boxes,
  Gauge,
  HardDrive,
  History,
  LayoutDashboard,
  LogOut,
  PackageSearch,
  ScrollText,
  ServerCog,
  Share2,
  Sparkles,
  TerminalSquare,
  UserRound,
} from 'lucide-react'

export type ViewName =
  | 'overview'
  | 'software'
  | 'startup'
  | 'system'
  | 'storage'
  | 'shares'
  | 'maintenance'
  | 'web'
  | 'terminal'
  | 'logs'
  | 'audit'
  | 'update'

interface SidebarProps {
  activeView: ViewName
  username: string
  onView: (view: ViewName) => void
  onLogout: () => void
}

const navigation = [
  { id: 'overview' as const, label: '总览', icon: LayoutDashboard },
  { id: 'software' as const, label: '软件', icon: PackageSearch },
  { id: 'startup' as const, label: '自启动', icon: Boxes },
  { id: 'system' as const, label: '系统', icon: Gauge },
  { id: 'storage' as const, label: '存储', icon: HardDrive },
  { id: 'shares' as const, label: '共享', icon: Share2 },
  { id: 'maintenance' as const, label: '维护', icon: Sparkles },
  { id: 'web' as const, label: 'Web 服务', icon: AppWindow },
  { id: 'terminal' as const, label: '终端', icon: TerminalSquare },
  { id: 'logs' as const, label: '日志', icon: ScrollText },
  { id: 'audit' as const, label: '审计', icon: History },
  { id: 'update' as const, label: '更新', icon: ArrowUpCircle },
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
