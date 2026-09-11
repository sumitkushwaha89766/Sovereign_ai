// Sovereignty endpoint. Live: GET /sovereignty/status (admin) ->
// { external_calls, internet_status, local_model_calls, documents_processed, sandbox_executions }.
import { api, USE_MOCKS, delay } from './client'
import { MOCK_SOVEREIGNTY } from './mocks'

export async function getSovereigntyStatus() {
  if (USE_MOCKS) {
    await delay(300)
    return { ...MOCK_SOVEREIGNTY }
  }
  const { data } = await api.get('/sovereignty/status')
  return data
}

export async function runSovereigntyProbe() {
  if (USE_MOCKS) {
    await delay(300)
    return { all_blocked: true }
  }
  const { data } = await api.post('/sovereignty/probe')
  return data
}
