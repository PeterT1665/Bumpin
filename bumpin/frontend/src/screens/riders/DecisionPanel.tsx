import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '@/api/client'
import type { TicketDetail } from '@/api/types'
import { Panel } from './rail'
import s from './DecisionPanel.module.css'

/* The verdict on a whole rider. Approving reserves the matched equipment for the
   set, which is what the Equipment screen's "Reserved" column reads. The backend
   refuses an approve while a conflict is open; that refusal becomes an override
   field rather than a dead end. Rejecting drafts a reply that says why, and
   nothing is sent until a person sends it. */

type Mode = 'idle' | 'reject' | 'override'

const cap = (v: string | null) => (v ? v[0].toUpperCase() + v.slice(1) : '')

function when(iso: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso
    : d.toLocaleString('en-AU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function DecisionPanel({ ticket, onDecided, onViewDraft }: {
  ticket: TicketDetail
  onDecided: (fresh: TicketDetail) => void
  onViewDraft: () => void
}) {
  const [mode, setMode] = useState<Mode>('idle')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (fn: () => Promise<TicketDetail>) => {
    setBusy(true)
    setError(null)
    try {
      onDecided(await fn())
      setMode('idle')
      setReason('')
    } catch (e) {
      if (e instanceof ApiError && e.isAlreadyDecided) {
        setError(`Already decided by ${cap(e.decidedBy ?? null)} at ${when(e.decidedAt ?? null)}.`)
        try { onDecided(await api.ticket(ticket.id)) } catch { /* keep what is on screen */ }
      } else if (e instanceof ApiError && e.isBlockedByConflict) {
        setError(`${e.detail} To approve anyway, say why.`)
        setMode('override')
      } else {
        setError(e instanceof Error ? e.message : 'That did not go through.')
      }
    } finally {
      setBusy(false)
    }
  }

  if (ticket.status === 'approved' || ticket.status === 'rejected') {
    const approved = ticket.status === 'approved'
    return (
      <Panel>
        <h2 className={`${s.title} t-label-md`}>Decision</h2>
        <p className={`${s.verdict} ${approved ? s.ok : s.no} t-label-md`}>
          {approved ? 'Rider approved' : 'Rider rejected'}
          {ticket.decided_by ? ` by ${cap(ticket.decided_by)}` : ''}
          {ticket.decided_at ? `, ${when(ticket.decided_at)}` : ''}
        </p>
        {approved
          ? <p className={`${s.hint} t-body-sm`}>Its equipment is reserved for the set. <Link to="/equipment">See Equipment</Link></p>
          : ticket.draft_email && ticket.draft_email.status === 'draft' && (
            <button type="button" className={`${s.btn} ${s.outline} t-label-md`} onClick={onViewDraft}>
              Review the drafted reply
            </button>
          )}
      </Panel>
    )
  }

  const confirm = mode === 'reject'
    ? () => run(() => api.reject(ticket.id, reason.trim()))
    : () => run(() => api.approve(ticket.id, reason.trim()))

  return (
    <Panel>
      <h2 className={`${s.title} t-label-md`}>Decision</h2>
      <p className={`${s.hint} t-body-sm`}>
        Approving reserves this rider's equipment for the set. Rejecting drafts a reply saying why.
      </p>
      {error && <p className={`${s.error} t-body-sm`} role="alert">{error}</p>}
      {mode === 'idle' ? (
        <div className={s.row}>
          <button type="button" className={`${s.btn} ${s.filled} t-label-md`} disabled={busy}
                  onClick={() => run(() => api.approve(ticket.id))}>
            {busy ? 'Approving…' : 'Approve rider'}
          </button>
          <button type="button" className={`${s.btn} ${s.outline} t-label-md`} disabled={busy}
                  onClick={() => { setMode('reject'); setError(null) }}>
            Reject
          </button>
        </div>
      ) : (
        <>
          <textarea className={`${s.input} t-body-sm`} rows={3} value={reason}
                    placeholder={mode === 'reject' ? 'Why this rider is rejected' : 'Why it is approved anyway'}
                    aria-label={mode === 'reject' ? 'Reason for rejecting' : 'Reason for approving anyway'}
                    onChange={(e) => setReason(e.target.value)} />
          <div className={s.row}>
            <button type="button" className={`${s.btn} ${s.filled} t-label-md`}
                    disabled={busy || !reason.trim()} onClick={confirm}>
              {mode === 'reject' ? 'Confirm reject' : 'Approve anyway'}
            </button>
            <button type="button" className={`${s.btn} ${s.outline} t-label-md`} disabled={busy}
                    onClick={() => { setMode('idle'); setReason(''); setError(null) }}>
              Cancel
            </button>
          </div>
        </>
      )}
    </Panel>
  )
}
