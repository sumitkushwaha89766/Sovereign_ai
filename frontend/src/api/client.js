// Axios client + the mock/live switch that is the Phase 5 -> Phase 6 seam.
//
// Sovereignty: baseURL is localhost-only (Architecture 4.1). No other hosts appear
// anywhere in the frontend. Mock mode is the zero-config default so Phase 5 runs with
// no backend; set VITE_USE_MOCKS=false to exercise the live Phase 4 API (Phase 6).
import axios from 'axios'

export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

// Default to mock unless explicitly disabled — Phase 5 works out of the box.
const mockMode = import.meta.env.VITE_USE_MOCKS ?? import.meta.env.VITE_USE_MOCK ?? 'true'
export const USE_MOCKS = mockMode !== 'false'

const TOKEN_KEY = 'sov_token'
export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (token) => {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export const api = axios.create({ baseURL: API_BASE, timeout: 15000 })

// Attach the JWT to every request (RBAC per Architecture 6).
api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Let the app react to an expired/invalid token (redirect to login).
let onUnauthorized = null
export const setUnauthorizedHandler = (fn) => {
  onUnauthorized = fn
}
api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error?.response?.status === 401 && typeof onUnauthorized === 'function') onUnauthorized()
    return Promise.reject(error)
  },
)

// Simulated latency so mock mode feels like a real async pipeline.
export const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
