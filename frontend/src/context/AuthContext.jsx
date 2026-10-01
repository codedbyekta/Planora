/**
 * context/AuthContext.jsx
 * ------------------------
 * Plain React Context (no Redux needed for something this small).
 * Holds the current user and JWT token, and exposes login/register/logout
 * functions that any component can call via useAuth().
 *
 * Token is persisted in localStorage so the user stays logged in
 * across page refreshes. On first load we check for a saved token
 * and, if present, fetch /me to restore the user object.
 */

import { createContext, useContext, useState, useEffect } from 'react'
import api from '../services/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) {
      setLoading(false)
      return
    }
    api
      .get('/me')
      .then((res) => setUser(res.data))
      .catch(() => localStorage.removeItem('token'))
      .finally(() => setLoading(false))
  }, [])

  async function login(email, password) {
    // The backend login route uses OAuth2PasswordRequestForm, which
    // expects standard form-encoded data, NOT JSON.
    const form = new URLSearchParams()
    form.append('username', email) // FastAPI's form field is called "username"
    form.append('password', password)

    const res = await api.post('/auth/login', form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })

    localStorage.setItem('token', res.data.access_token)
    const meRes = await api.get('/me')
    setUser(meRes.data)
  }

  async function register(name, email, password) {
    await api.post('/auth/register', { name, email, password })
    // Automatically log in right after registering
    await login(email, password)
  }

  function logout() {
    localStorage.removeItem('token')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
