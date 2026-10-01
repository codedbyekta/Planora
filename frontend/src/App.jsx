import { Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import Tasks from './pages/Tasks'
import FocusTimer from './pages/FocusTimer'
import Recommendations from './pages/Recommendations'
import Schedule from './pages/Schedule'
import Analytics from './pages/Analytics'
import Calendar from './pages/Calendar'
import WeeklyReport from './pages/WeeklyReport'
import ProtectedRoute from './components/ProtectedRoute'
import Layout from './components/Layout'
import { TimerProvider } from './context/TimerContext'

function Protected({ children }) {
  return (
    <ProtectedRoute>
      <Layout>{children}</Layout>
    </ProtectedRoute>
  )
}

export default function App() {
  return (
    <TimerProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />

        <Route
          path="/dashboard"
          element={
            <Protected>
              <Dashboard />
            </Protected>
          }
        />

        <Route
          path="/tasks"
          element={
            <Protected>
              <Tasks />
            </Protected>
          }
        />

        <Route
          path="/session"
          element={
            <Protected>
              <FocusTimer />
            </Protected>
          }
        />

        <Route
          path="/recommendations"
          element={
            <Protected>
              <Recommendations />
            </Protected>
          }
        />

        <Route
          path="/schedule"
          element={
            <Protected>
              <Schedule />
            </Protected>
          }
        />

        <Route
          path="/analytics"
          element={
            <Protected>
              <Analytics />
            </Protected>
          }
        />

        <Route
          path="/calendar"
          element={
            <Protected>
              <Calendar />
            </Protected>
          }
        />

        <Route
          path="/report"
          element={
            <Protected>
              <WeeklyReport />
            </Protected>
          }
        />

        <Route
          path="/"
          element={<Navigate to="/dashboard" replace />}
        />

        <Route
          path="*"
          element={<Navigate to="/dashboard" replace />}
        />
      </Routes>
    </TimerProvider>
  )
}