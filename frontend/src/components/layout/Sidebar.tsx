import { NavLink } from 'react-router-dom'
import { useAuthStore } from '../../stores/authStore'
import { MessageSquare, Settings, LogOut } from 'lucide-react'

export function Sidebar() {
  const { user, signOut } = useAuthStore()

  const navItems = [
    { label: 'Chat & Log', path: '/chat', icon: MessageSquare },
    { label: 'Settings', path: '/settings', icon: Settings },
  ]

  return (
    <aside className="w-60 bg-surface border-r border-sand-border p-6 flex-col justify-between hidden md:flex h-screen sticky top-0">
      <div className="flex flex-col gap-10">
        {/* Navigation */}
        <nav className="flex flex-col gap-1">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `press flex items-center gap-3 px-4 py-2.5 rounded-full text-sm font-medium ${
                  isActive
                    ? 'bg-sage text-white'
                    : 'text-muted hover:text-ink hover:bg-container'
                }`
              }
            >
              <item.icon className="w-4 h-4" strokeWidth={1.75} />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>

      {/* User footer */}
      <div className="border-t border-sand-border pt-4 flex flex-col gap-3">
        <div className="flex items-center gap-3 px-2">
          <div className="w-8 h-8 rounded-full bg-sand border border-sand-border flex items-center justify-center font-semibold text-xs text-sage-deep">
            {user?.email?.[0].toUpperCase() || 'U'}
          </div>
          <div className="overflow-hidden">
            <h4 className="text-xs font-semibold text-ink truncate">{user?.name || 'User'}</h4>
            <p className="text-[11px] text-muted truncate">{user?.email}</p>
          </div>
        </div>
        <button
          onClick={signOut}
          className="press flex items-center gap-3 px-4 py-2.5 rounded-full text-sm font-medium text-muted hover:text-danger hover:bg-container w-full text-left"
        >
          <LogOut className="w-4 h-4" strokeWidth={1.75} />
          Sign Out
        </button>
      </div>
    </aside>
  )
}
