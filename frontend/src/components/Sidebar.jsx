import { NavLink } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const links = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/tasks', label: 'Tasks' },
  { to: '/session', label: 'Focus Session' },
  { to: '/recommendations', label: 'Recommendations' },
  { to: '/schedule', label: 'Schedule' },
  { to: '/analytics', label: 'Analytics' },
  { to: '/calendar', label: 'Calendar' },
  { to: '/report', label: 'Weekly Report' },
]

export default function Sidebar() {
  const { user, logout } = useAuth()

  return (
    <aside className="flex h-screen w-56 flex-col justify-between border-r border-border bg-card px-4 py-6">
      <div>
        <div className="mb-8 px-2">
          <h1 className="font-display text-lg font-semibold text-ink">Planora</h1>
          <p className="text-xs text-ink/50">Plan tomorrow around you</p>
        </div>

        <nav className="flex flex-col gap-1">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) =>
                `rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-primary-light text-primary'
                    : 'text-ink/60 hover:bg-surface hover:text-ink'
                }`
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
      </div>

      <div className="px-2">
        <p className="mb-2 truncate text-xs text-ink/50">{user?.email}</p>
        <button
          onClick={logout}
          className="w-full rounded-lg border border-border px-3 py-2 text-sm font-medium text-ink/70 hover:bg-surface"
        >
          Log out
        </button>
      </div>
    </aside>
  )
}
