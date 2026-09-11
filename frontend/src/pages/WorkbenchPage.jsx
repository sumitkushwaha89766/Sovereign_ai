// Flagship Workbench (the MVP demo surface). Pick a scanned document, state a goal,
// run the local agent, watch the pipeline steps + model routing, read the grounded
// evidence, and approve to produce the deliverable. No websockets — status is polled
// (Architecture §4.2). Everything is local (sovereignty).
//
// All state (documents, selected doc, goal, run, evidence) is persisted to
// localStorage so page reloads and tab switches do not lose progress.
import { useEffect, useState } from 'react'
import { runAgent } from '../api/agent'
import { uploadDocument } from '../api/documents'
import { decideApproval } from '../api/approval'
import { USE_MOCKS } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useWorkbenchState } from '../hooks/useWorkbenchState'
import FileUpload from '../components/FileUpload'
import DocumentsList from '../components/DocumentsList'
import RunSteps from '../components/RunSteps'
import EvidencePanel from '../components/EvidencePanel'
import ApprovalModal from '../components/ApprovalModal'
import StatusLight from '../components/StatusLight'

const TERMINAL = ['awaiting_approval', 'approved', 'rejected', 'complete', 'failed']

const STATUS_STATE = {
  in_progress: 'active',
  awaiting_approval: 'caution',
  approved: 'nominal',
  rejected: 'trip',
  failed: 'trip',
}

export default function WorkbenchPage() {
  const { role } = useAuth()
  const canRun = role === 'engineer' || role === 'admin'

  const {
    documents, setDocuments,
    selectedId, setSelectedId,
    goal, setGoal,
    run, setRun,
    runStatus, setRunStatus,
    runError, setRunError,
  } = useWorkbenchState()

  const [starting, setStarting] = useState(false)
  const [approvalOpen, setApprovalOpen] = useState(false)
  const [approvalBusy, setApprovalBusy] = useState(false)
  const [approvalResult, setApprovalResult] = useState(null)
  const [slowRunNote, setSlowRunNote] = useState(false)

  // Poll run status until terminal state. Uses adaptive interval:
  // fast (1.5s) for first 20 polls, then slow (3s) to avoid hammering.
  // Cap at 200 polls (~8 min) — the planner can take 60-90s on cold Ollama.
  useEffect(() => {
    if (!run) return
    const currentStatus = runStatus?.status
    // If the stored status is already terminal, don't restart polling
    if (currentStatus && TERMINAL.includes(currentStatus)) return

    let cancelled = false
    let polls = 0
    let timer

    const tick = async () => {
      polls += 1
      try {
        const { getRunStatus } = await import('../api/agent')
        const status = await getRunStatus(run.agent_run_id)
        if (cancelled) return
        setRunStatus(status)
        if (TERMINAL.includes(status.status)) return
        if (polls >= 200) {
          setRunError('The agent run is taking longer than expected. Check the backend terminal for PLANNER_STEP logs.')
          return
        }
        const interval = polls < 20 ? 1500 : 3000
        timer = setTimeout(tick, interval)
      } catch {
        if (!cancelled) setRunError('Failed to fetch run status — backend may have restarted.')
      }
    }
    timer = setTimeout(tick, 600)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [run]) // eslint-disable-line react-hooks/exhaustive-deps

  // Show 'still running' hint after 15s with no terminal status
  const status = runStatus?.status
  const running = Boolean(run) && (!status || status === 'in_progress')
  useEffect(() => {
    if (!running) { setSlowRunNote(false); return }
    const t = setTimeout(() => setSlowRunNote(true), 15000)
    return () => clearTimeout(t)
  }, [running])

  async function handleRun() {
    setStarting(true)
    setRunError(null)
    setRunStatus(null)
    setApprovalResult(null)
    setSlowRunNote(false)
    try {
      const started = await runAgent({ goal, document_id: selectedId })
      setRun(started)
    } catch {
      setRunError('Could not start the run. Check that the backend is running and you have the engineer role.')
    } finally {
      setStarting(false)
    }
  }

  function handleUploaded(doc) {
    setDocuments((prev) => [doc, ...prev.filter((d) => d.document_id !== doc.document_id)])
    setSelectedId(doc.document_id)
  }

  async function handleDecide(decision, comment) {
    setApprovalBusy(true)
    try {
      const result = await decideApproval(runStatus?.approval_id, decision, comment)
      setApprovalResult(result)
      setRunStatus((prev) => (
        prev
          ? { ...prev, status: result.status, approval_status: result.status }
          : prev
      ))
    } catch {
      setApprovalResult({ status: 'error', output_file: null })
    } finally {
      setApprovalBusy(false)
    }
  }

  const awaitingApproval = status === 'awaiting_approval'
  const evidenceEmptyMsg = USE_MOCKS
    ? undefined
    : 'The agent pipeline (OCR → retrieve → reason) is implemented in Phase 7. Live runs return grounded evidence then.'

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="eyebrow">Agentic workbench</div>
        <h1 className="text-xl text-text">Inspection review</h1>
      </div>

      {/* Mission bar: goal + run */}
      <section className="panel p-4">
        <label className="field-label" htmlFor="goal">
          Goal
        </label>
        <textarea
          id="goal"
          className="input mb-3"
          rows={2}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="Describe the task for the agent…"
        />
        <div className="flex flex-wrap items-center gap-3">
          <span className="chip">
            <span className="text-muted">document</span>
            <span className="text-accent">#{selectedId ?? '—'}</span>
          </span>
          <button
            className="btn btn-primary ml-auto"
            onClick={handleRun}
            disabled={!canRun || !goal.trim() || !selectedId || starting || running}
          >
            {starting || running ? 'Running…' : 'Run agent'}
          </button>
        </div>
        {!canRun && (
          <p className="mt-2 text-xs text-caution">Your role can view runs but not start them (engineer role required).</p>
        )}
        {runError && <p className="mt-2 text-sm text-trip">{runError}</p>}
        {slowRunNote && !runError && (
          <p className="mt-2 text-xs text-muted">
            ⏳ Pipeline running — this takes 30–90 s while the local model processes the document. Watch the backend terminal for <code>PLANNER_STEP</code> logs.
          </p>
        )}
        {run && !running && !runError && (
          <p className="mt-2 text-xs text-muted">
            Last run: <span className="text-accent">#{run.agent_run_id}</span> — status preserved across reloads.
          </p>
        )}
      </section>

      <div className="grid gap-5 lg:grid-cols-[minmax(260px,1fr)_minmax(240px,320px)_minmax(320px,1.4fr)]">
        {/* Documents */}
        <section className="panel p-4 flex flex-col gap-4">
          <div>
            <div className="field-label mb-2">Upload document</div>
            <FileUpload onUploaded={handleUploaded} />
          </div>
          <div>
            <div className="field-label mb-2">Local documents</div>
            <DocumentsList documents={documents} selectedId={selectedId} onSelect={(d) => setSelectedId(d.document_id)} />
          </div>
        </section>

        {/* Run steps rail */}
        <section className="panel p-4 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <div className="field-label">Pipeline</div>
            {run && (
              <span className="chip">
                run <span className="text-accent">#{run.agent_run_id}</span>
              </span>
            )}
          </div>
          {run ? (
            <>
              <RunSteps
                status={status}
                steps_completed={runStatus?.steps_completed}
                model_used={runStatus?.model_used}
              />
              <div className="pt-2 border-t border-border">
                <StatusLight
                  state={STATUS_STATE[status] || 'idle'}
                  label={(status || 'starting').replace(/_/g, ' ')}
                />
              </div>
            </>
          ) : (
            <p className="text-sm text-muted py-4">Run the agent to see the pipeline and model routing.</p>
          )}
        </section>

        {/* Evidence */}
        <section className="panel p-4 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <div className="field-label">Evidence &amp; citations</div>
            {awaitingApproval && (
              <button className="btn btn-approve" onClick={() => setApprovalOpen(true)}>
                Review &amp; approve
              </button>
            )}
            {status === 'approved' && approvalResult?.output_file && (
              <span className="chip text-nominal">{approvalResult.output_file}</span>
            )}
          </div>
          <EvidencePanel evidence={runStatus?.evidence} emptyMessage={run ? evidenceEmptyMsg : undefined} />
        </section>
      </div>

      <ApprovalModal
        open={approvalOpen}
        onClose={() => setApprovalOpen(false)}
        busy={approvalBusy}
        result={approvalResult}
        onDecide={handleDecide}
        item={{
          action: 'Export approval note',
          agent_run_id: run?.agent_run_id,
          requested_by: 'this run',
        }}
      />
    </div>
  )
}
