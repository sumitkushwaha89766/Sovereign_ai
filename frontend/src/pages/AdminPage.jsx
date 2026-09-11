// Admin (admin-only). Users register + audit log. The log is also sovereignty evidence:
// a blocked external attempt is surfaced explicitly. Mock-only surface — no Phase 4
// /admin endpoint backs it yet, so live mode shows empty tables.
import { useEffect, useState } from 'react'
import { listUsers, listAuditLog } from '../api/admin'

const ROLE_TONE = { engineer: 'text-accent', approver: 'text-caution', admin: 'text-nominal' }

function eventState(row) {
  if (row.external_attempt_blocked) return 'caution'
  if (row.event_type === 'document_upload') return 'nominal'
  return 'accent'
}

export default function AdminPage() {
  const [users, setUsers] = useState([])
  const [log, setLog] = useState([])

  useEffect(() => {
    let alive = true
    Promise.all([listUsers(), listAuditLog()]).then(([u, l]) => {
      if (!alive) return
      setUsers(u)
      setLog(l)
    })
    return () => {
      alive = false
    }
  }, [])

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="eyebrow">Administration</div>
        <h1 className="text-xl text-text">Users &amp; audit log</h1>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(280px,1fr)_minmax(360px,1.6fr)]">
        {/* Users */}
        <section className="panel overflow-hidden">
          <div className="px-4 py-2 border-b border-border eyebrow">Users</div>
          {users.length === 0 ? (
            <div className="px-4 py-6 text-sm text-muted">No users to display.</div>
          ) : (
            users.map((u) => (
              <div
                key={u.username}
                className="flex items-center gap-3 px-4 py-3 border-b border-border last:border-0"
              >
                <span className="led led-nominal" aria-hidden="true" />
                <span className="text-sm text-text">{u.username}</span>
                <span className={`mono text-xs uppercase ml-auto ${ROLE_TONE[u.role] || 'text-muted'}`}>
                  {u.role}
                </span>
                <span className="mono text-xs text-muted">{u.status}</span>
              </div>
            ))
          )}
        </section>

        {/* Audit log */}
        <section className="panel overflow-hidden">
          <div className="px-4 py-2 border-b border-border eyebrow">Audit log</div>
          {log.length === 0 ? (
            <div className="px-4 py-6 text-sm text-muted">No log entries.</div>
          ) : (
            log.map((row, i) => (
              <div
                key={i}
                className="grid grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-2.5 border-b border-border last:border-0"
              >
                <span className={`led led-${eventState(row)}`} aria-hidden="true" />
                <div className="min-w-0">
                  <div className="mono text-xs text-text truncate">{row.event_type}</div>
                  <div className="text-xs text-muted truncate">{row.detail}</div>
                </div>
                <div className="text-right">
                  {row.external_attempt_blocked ? (
                    <span className="chip text-caution">egress blocked</span>
                  ) : (
                    <span className="mono text-xs text-muted">local</span>
                  )}
                </div>
              </div>
            ))
          )}
        </section>
      </div>
    </div>
  )
}
