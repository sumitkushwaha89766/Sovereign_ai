// Admin surface. No Phase 4 endpoint backs this yet, so it is mock-only; the
// signatures stay stable so a future /admin/* backend is a drop-in flip.
import { USE_MOCKS, delay } from './client'
import { MOCK_ADMIN_USERS, MOCK_AUDIT_LOG } from './mocks'

export async function listUsers() {
  if (USE_MOCKS) {
    await delay(200)
    return [...MOCK_ADMIN_USERS]
  }
  const { data } = await api.get('/admin/users')
  return data
}

export async function listAuditLog() {
  if (USE_MOCKS) {
    await delay(200)
    return [...MOCK_AUDIT_LOG]
  }
  const { data } = await api.get('/admin/audit')
  return data
}
