/**
 * services/api.js
 * ----------------
 * A single configured Axios instance used everywhere in the app.
 *
 * - `baseURL` points at the FastAPI backend.
 * - The request interceptor automatically attaches the JWT token
 *   (read from localStorage) to every outgoing request, so individual
 *   components never have to remember to add the Authorization header.
 * - The response interceptor logs the user out automatically if the
 *   backend ever responds with 401 (expired/invalid token).
 */

import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api
