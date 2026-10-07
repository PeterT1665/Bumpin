import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/primitives'
import { ApiError, api } from '@/api/client'
import type { DraftEmail } from '@/api/types'
import s from './vendors.module.css'

/** Figma 204:178 — "Bumpin — Resolve · Vendor".
 *
 *  Scrim 204:333 covers the canvas but not the rail (#1a1614 @ 0.4). Modal
 *  204:334 is 640x742, r 24, with two drop shadows. Head 204:335 (pad 28/32/24),
 *  then three 52px field rows separated by full-bleed hairlines, then the body
 *  section 204:352 (pad 24/32/28) holding the editable email 204:353 and the
 *  right-aligned action row 204:359.
 *
 *  Nothing sends itself. The draft already exists in the outbox; this saves the
 *  operator's edits with `PATCH /outbox/{id}` and only then, on an explicit
 *  press of Send, calls `POST /outbox/{id}/send`. */
export function ResolveModal({ draft, cc, onClose, onSent }: {
  draft: DraftEmail
  /** Shown on the Cc row the design carries. The backend's outbox row has no Cc
   *  field, so this is the operator the app runs as. */
  cc: string
  onClose: () => void
  onSent: () => void
}) {
  const [subject, setSubject] = useState(draft.subject)
  const [body, setBody] = useState(draft.body)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => { closeRef.current?.focus() }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const sent = draft.status === 'sent'
  const dirty = subject !== draft.subject || body !== draft.body

  async function send() {
    setBusy(true)
    setError(null)
    try {
      if (dirty) await api.updateDraft(draft.outbox_id, { subject, body })
      await api.send(draft.outbox_id)
      onSent()
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.isAlreadyDecided
            ? `Already decided by ${e.decidedBy} at ${e.decidedAt}.`
            : e.detail
          : 'Could not send the draft.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={s.scrim} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div
        className={s.modal}
        role="dialog"
        aria-modal="true"
        aria-labelledby="resolve-title"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* 204:335 Head */}
        <header className={s.modalHead}>
          <h2 id="resolve-title" className={`${s.modalTitle} t-heading-md`}>Resolve conflicts</h2>
          <button ref={closeRef} className={s.modalClose} onClick={onClose} aria-label="Close">×</button>
        </header>

        {/* 204:340 / 204:344 / 204:348 — To, Cc, Subject */}
        <div className={s.field}>
          <span className={`${s.fieldLabel} t-label-sm`}>To</span>
          <span className={`${s.fieldValue} t-body-md`}>{draft.to}</span>
        </div>
        <div className={s.field}>
          <span className={`${s.fieldLabel} t-label-sm`}>Cc</span>
          <span className={`${s.fieldValue} t-body-md`}>{cc}</span>
        </div>
        <label className={s.field}>
          <span className={`${s.fieldLabel} t-label-sm`}>Subject</span>
          <input
            className={s.fieldInput}
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            disabled={sent || busy}
          />
        </label>

        {/* 204:352 Body section */}
        <div className={s.modalBody}>
          <textarea
            className={`${s.emailBox} t-body-md`}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            disabled={sent || busy}
            aria-label="Email body"
          />

          {error && <p className={`${s.error} t-body-sm`}>{error}</p>}

          {/* 204:359 Actions */}
          <div className={s.modalActions}>
            <span className={s.modalCaption}>
              {draft.context_used.length > 0 && (
                <span
                  className={`${s.modalContext} t-caption`}
                  title={draft.context_used.join(' · ')}
                >
                  Read: {draft.context_used.join(' · ')}
                </span>
              )}
              <span className={`${s.modalNote} t-caption`}>
                {sent
                  ? 'This reply has already been sent.'
                  : 'Saved as a draft until you press Send.'}
              </span>
            </span>
            <span className={s.modalActionsRight}>
              {/* 204:360 Send sits before 204:362 Cancel in the design */}
              <Button onClick={send} disabled={sent || busy}>{busy ? 'Sending…' : 'Send'}</Button>
              <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
