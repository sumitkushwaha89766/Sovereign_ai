// Sovereignty Dashboard (admin). The proof surface: zero external calls is the headline.
// Per dataviz guidance these are stat tiles / hero numbers, not charts — a scalar count
// has no honest time series to plot. `internet_status: blocked` is the DESIRED state, so
// it reads as nominal (good) with an LED + label, never color alone.
import { useEffect, useState } from 'react'
import { getSovereigntyStatus, runSovereigntyProbe } from '../api/sovereignty'
import KpiTile from '../components/KpiTile'
import StatusLight from '../components/StatusLight'

export default function SovereigntyDashboard() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const loadStatus = async (probe = false) => {
    setLoading(true)
    setError(null)
    try {
      if (probe) await runSovereigntyProbe()
      setData(await getSovereigntyStatus())
    } catch {
      setError('Could not verify sovereignty status. Admin role and a running backend are required.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let alive = true
    getSovereigntyStatus()
      .then((d) => alive && setData(d))
      .catch(() => alive && setError('Could not load sovereignty status. Admin role and a running backend are required.'))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])

  const externalCalls = data?.external_calls ?? data?.external_api_calls
  const clean = externalCalls === 0
  const blocked = data?.internet_status === 'blocked'
  const probe = data?.last_isolation_probe

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="eyebrow">Proof of sovereignty</div>
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-xl text-text">Sovereignty dashboard</h1>
          <button
            type="button"
            className="btn btn-ghost shrink-0"
            onClick={() => loadStatus(true)}
            disabled={loading}
          >
            {loading ? 'Checking…' : 'Refresh proof'}
          </button>
        </div>
      </div>

      {loading && <div className="panel p-6 text-sm text-muted">Reading local telemetry…</div>}
      {error && <div className="panel p-6 text-sm text-trip">{error}</div>}

      {data && (
        <>
          {/* Hero proof + internet posture */}
          <div className="grid gap-4 md:grid-cols-3">
            <div className="panel p-6 md:col-span-2 flex flex-col justify-between">
              <div className="eyebrow">External network calls · since boot</div>
              <div className="flex items-end gap-4 mt-4">
                <span className={`mono text-7xl leading-none ${clean ? 'text-nominal' : 'text-trip'}`}>
                  {externalCalls ?? '—'}
                </span>
                <StatusLight
                  state={clean ? 'nominal' : 'trip'}
                  label={clean ? 'no egress detected' : 'egress detected — investigate'}
                  className="mb-2"
                />
              </div>
              <p className="text-sm text-muted mt-4">
                Every model, OCR, and embedding call runs on this machine. A non-zero value would falsify the
                air-gap — this counter is the claim.
              </p>
            </div>

            <div className="panel p-6 flex flex-col justify-between">
              <div className="eyebrow">Internet egress</div>
              <div className="flex items-center gap-3 mt-4">
                <StatusLight state={blocked ? 'nominal' : 'trip'} />
                <span className={`mono text-2xl uppercase ${blocked ? 'text-nominal' : 'text-trip'}`}>
                  {data.internet_status}
                </span>
              </div>
              <p className="text-sm text-muted mt-4">
                {blocked
                  ? 'OS-level isolation probe confirmed all monitored cloud targets are unreachable.'
                  : 'The latest OS-level isolation probe did not prove that all monitored cloud targets are unreachable.'}
              </p>
              <div className="mono text-xs text-muted mt-2">
                Blocked attempts: {data.blocked_attempt_count ?? 0}
              </div>
            </div>
          </div>

          {/* Local activity counts */}
          <div className="grid gap-4 sm:grid-cols-3">
            <KpiTile
              label="Local model calls"
              value={data.local_model_calls}
              tone="accent"
              note="On-device inference (Ollama / vLLM)"
            />
            <KpiTile
              label="Documents processed"
              value={data.documents_processed}
              tone="neutral"
              note="Local OCR + parsing"
            />
            <KpiTile
              label="Sandbox executions"
              value={data.sandbox_executions}
              tone="neutral"
              note="Isolated, no-network container"
            />
          </div>

          {/* How it's proven */}
          <section className="panel p-4">
            <div className="field-label mb-3">How this is enforced</div>
            <ul className="grid gap-2 sm:grid-cols-3 text-sm text-muted">
              <li className="flex items-start gap-2">
                <span className="led led-nominal mt-1.5" aria-hidden="true" />
                Container runs with no network route; egress attempts are denied and logged.
              </li>
              <li className="flex items-start gap-2">
                <span className="led led-nominal mt-1.5" aria-hidden="true" />
                Models, OCR, and embeddings are local weights — no cloud APIs.
              </li>
              <li className="flex items-start gap-2">
                <span className="led led-nominal mt-1.5" aria-hidden="true" />
                The audit log (Admin) records every call and any blocked external attempt.
              </li>
            </ul>
          </section>

          <section className="panel p-4">
            <div className="field-label mb-2">Isolation probe</div>
            <div className="text-sm text-muted">
              {probe?.proof || 'No OS-level isolation probe has been recorded yet.'}
            </div>
            {probe?.timestamp && (
              <div className="mono text-xs text-muted mt-2">Last checked: {probe.timestamp}</div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
