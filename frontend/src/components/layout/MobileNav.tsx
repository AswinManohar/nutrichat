import { NavLink } from 'react-router-dom'
import { MessageSquare, Settings } from 'lucide-react'

export function MobileNav() {
  const navItems = [
    { label: 'Chat', path: '/chat', icon: MessageSquare },
    { label: 'Settings', path: '/settings', icon: Settings },
  ]

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 glass-header border-t border-sand-border z-40 flex items-center justify-around pt-2 pb-5 px-6">
      {navItems.map((item) => (
        <NavLink
          key={item.path}
          to={item.path}
          className={({ isActive }) =>
            `press flex flex-col items-center gap-0.5 py-1.5 px-5 rounded-full ${
              isActive ? 'bg-sage text-white' : 'text-muted hover:text-ink'
            }`
          }
        >
          <item.icon className="w-5 h-5" strokeWidth={1.75} />
          <span className="text-[10px] font-medium">{item.label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
