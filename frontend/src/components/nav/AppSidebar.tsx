import { Link, useLocation } from 'react-router-dom'
import { MessageSquare, Clock, BarChart2, BookMarked } from 'lucide-react'

const NAV_ITEMS = [
  { icon: MessageSquare, label: 'Chat',      to: '/chat'    },
  { icon: Clock,         label: 'History',   to: '/chat'    },  // placeholder until /history exists
  { icon: BarChart2,     label: 'Trends',    to: '/trends'  },
  { icon: BookMarked,    label: 'My Meals',  to: '/my-meals' },
] as const

export function AppSidebar() {
  const { pathname } = useLocation()

  return (
    <aside className="hidden md:flex w-[60px] h-screen flex-col items-center py-4 gap-2 bg-sage-forest flex-shrink-0 z-20">
      {/* Logo pill */}
      <div className="w-9 h-9 rounded-full bg-white/15 flex items-center justify-center mb-3">
        <span className="text-white font-display font-bold text-[15px] leading-none select-none">N</span>
      </div>

      {/* Nav icons */}
      <nav className="flex-1 flex flex-col items-center gap-1">
        {NAV_ITEMS.map(({ icon: Icon, label, to }) => {
          const active = pathname === to || (to === '/chat' && (pathname === '/' || pathname === '/chat')) ||
            (to === '/trends' && pathname === '/trends') ||
            (to === '/my-meals' && pathname === '/my-meals')
          return (
            <Link
              key={label}
              to={to}
              title={label}
              className={`w-10 h-10 rounded-xl flex items-center justify-center transition-colors duration-150 ${
                active
                  ? 'bg-white/20 text-white'
                  : 'text-white/40 hover:text-white/70 hover:bg-white/10'
              }`}
            >
              <Icon className="w-5 h-5" strokeWidth={1.75} />
            </Link>
          )
        })}
      </nav>

      {/* User avatar dot */}
      <div className="w-8 h-8 rounded-full bg-sage flex items-center justify-center mt-auto">
        <span className="text-white text-[11px] font-semibold select-none">A</span>
      </div>
    </aside>
  )
}
