// Approval endpoints. Live: POST /approval/{id}/decide { decision } ->
// { status, output_file }. Phase 4 has no pending-queue list endpoint, so the
// queue is a mock/demo surface; the decide call is wired for both modes.
import { api, USE_MOCKS, delay } from './client'
import { MOCK_APPROVALS, mockDecide } from './mocks'

export async function listPendingApprovals() {
  if (USE_MOCKS) {
    await delay(250)
    const items = [...MOCK_APPROVALS]
    const counts = {
      total: items.length,
      pending: items.filter((a) => a.status === 'pending').length,
      approved: items.filter((a) => a.status === 'approved').length,
      rejected: items.filter((a) => a.status === 'rejected').length,
      decided: items.filter((a) => a.status !== 'pending').length,
    }
    return { items, counts }
  }
  const { data } = await api.get('/approval/queue')
  return data
}

export async function decideApproval(approvalId, decision, comment) {
  if (USE_MOCKS) {
    await delay(400)
    return mockDecide(approvalId, decision)
  }
  const { data } = await api.post(`/approval/${approvalId}/decide`, { decision, comment })
  return data // { status, output_file }
}
