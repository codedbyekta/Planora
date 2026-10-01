import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

/**
 * Wraps any page that requires login. If there's no logged-in user
 * (and we're done checking localStorage), redirect to /login.
 */
export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth()

  if (loading) {
    return <div className="flex h-screen items-center justify-center text-ink/50">Loading…</div>
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return children
}
