// Approvals queue (Architecture §8, approver/admin). Lists pending agent outputs
// awaiting a human decision; deciding produces the deliverable (output_file) on approve.
// Phase 4 has no list endpoint, so live mode shows an empty queue until Phase 7.
import { useEffect, useState } from 'react'
import { listPendingApprovals, decideApproval } from '../api/approval'
import ApprovalModal from '../components/ApprovalModal'

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState([])
  const [counts, setCounts] = useState({ total: 0, pending: 0, approved: 0, rejected: 0, decided: 0 })
  const [loading, setLoading] = useState(true)
  const [active, setActive] = useState(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  useEffect(() => {
    let alive = true
    listPendingApprovals()
      .then((data) => {
        if (!alive) return
        setApprovals(data.items || [])
        setCounts(data.counts || { total: 0, pending: 0, approved: 0, rejected: 0, decided: 0 })
      })
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])

  async function handleDecide(decision) {
    if (!active) return
    setBusy(true)
    try {
      const res = await decideApproval(active.approval_id, decision)
      setResult(res)
      setApprovals((prev) => prev.map((item) => (
        item.approval_id === active.approval_id ? { ...item, status: res.status } : item
      )))
      setCounts((prev) => ({
        ...prev,
        pending: Math.max(0, prev.pending - 1),
        [res.status]: (prev[res.status] || 0) + 1,
        decided: prev.decided + 1,
      }))
    } catch {
      setResult({ status: 'error', output_file: null })
    } finally {
      setBusy(false)
    }
  }

  function openItem(item) {
    setActive(item)
    setResult(null)
    setBusy(false)
  }

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="eyebrow">Human-in-the-loop</div>
        <h1 className="text-xl text-text">Approvals queue</h1>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {[
          ['Total requests', counts.total],
          ['In queue', counts.pending],
          ['Approved', counts.approved],
          ['Rejected', counts.rejected],
          ['Completed', counts.decided],
        ].map(([label, value]) => (
          <div key={label} className="panel px-3 py-3">
            <div className="field-label">{label}</div>
            <div className="mono text-xl text-accent mt-1">{value}</div>
          </div>
        ))}
      </div>

      <section className="panel overflow-hidden">
        <div className="grid grid-cols-[80px_1fr_140px_120px] gap-3 px-4 py-2 border-b border-border eyebrow">
          <span>Run</span>
          <span>Action</span>
          <span>Requested by</span>
          <span className="text-right">Decision</span>
        </div>
        {loading ? (
          <div className="px-4 py-6 text-sm text-muted">Loading…</div>
        ) : approvals.length === 0 ? (
          <div className="px-4 py-6 text-sm text-muted">No approval requests yet.</div>
        ) : (
          approvals.map((a) => (
            <div
              key={a.approval_id}
              className="grid grid-cols-[80px_1fr_140px_120px] gap-3 px-4 py-3 border-b border-border last:border-0 items-center"
            >
              <span className="mono text-sm text-accent">#{a.agent_run_id}</span>
              <span className="text-sm text-text">{a.action}</span>
              <span className="mono text-sm text-muted">{a.requested_by}</span>
              <div className="text-right">
                {a.status === 'pending' ? (
                  <button className="btn btn-ghost" onClick={() => openItem(a)}>
                    Review
                  </button>
                ) : (
                  <span className={`chip ${a.status === 'approved' ? 'text-nominal' : 'text-trip'}`}>
                    {a.status}
                  </span>
                )}
              </div>
            </div>
          ))
        )}
      </section>

      <ApprovalModal
        open={Boolean(active)}
        onClose={() => setActive(null)}
        busy={busy}
        result={result}
        onDecide={handleDecide}
        item={active}
      />
    </div>
  )
}
