import { useEffect, useState } from 'react'
import { ACTOR } from '@/api/client'
import type { DraftEmail } from '@/api/types'
import s from './ResolveModal.module.css'

/* Figma 204:2: the scrim 204:177 plus the modal 159:414.
 *
 * The email is already in the outbox as a draft — approving wrote it there. This
 * modal only lets the operator read it, change the subject or body, and send it
 * by hand. Nothing here sends on its own. */

export function ResolveModal({ draft, busy, error, onSend, onClose }: {
  draft: DraftEmail
  busy: boolean
  error: string | null
  /** Saves any edit first, then sends. */
  onSend: (edits: { subject?: string; body?: string }) => void
  onClose: () => void
}) {
  const [subject, setSubject] = useState(draft.subject)
  const [body, setBody] = useState(draft.body)

  /* Seed once per draft so a background poll cannot wipe an edit in progress. */
  useEffect(() => { setSubject(draft.subject); setBody(draft.body) }, [draft.outbox_id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const send = () => {
    const edits: { subject?: string; body?: string } = {}
    if (subject !== draft.subject) edits.subject = subject
    if (body !== draft.body) edits.body = body
    onSend(edits)
  }

  return (
    <>
      <div className={s.scrim} onClick={onClose} aria-hidden />
      <div className={s.layer} role="dialog" aria-modal="true" aria-label="Resolve conflicts">
        <div className={s.modal}>
          <div className={s.head}>
            <div className={s.headRow}>
              <h2 className={`${s.title} t-heading-md`}>Resolve conflicts</h2>
              <button type="button" className={`${s.close} t-heading-md`} onClick={onClose}
                      aria-label="Close">&#215;</button>
            </div>
          </div>
          <div className={s.divider} aria-hidden />

          <div className={s.field}>
            <span className={`${s.fieldLabel} t-label-sm`}>To</span>
            <span className={`${s.fieldValue}`}>{draft.to}</span>
          </div>
          <div className={s.divider} aria-hidden />

          {/* The outbox row has no `cc`, so this is the single operator the build
              runs as (`ACTOR` in api/client.ts) rather than an invented address. */}
          <div className={s.field}>
            <span className={`${s.fieldLabel} t-label-sm`}>Cc</span>
            <span className={`${s.fieldValue}`}>{ACTOR.charAt(0).toUpperCase() + ACTOR.slice(1)}</span>
          </div>
          <div className={s.divider} aria-hidden />

          <div className={s.field}>
            <span className={`${s.fieldLabel} t-label-sm`}>Subject</span>
            <input className={s.fieldValue} value={subject} aria-label="Subject"
                   onChange={(e) => setSubject(e.target.value)} />
          </div>
          <div className={s.divider} aria-hidden />

          <div className={s.body}>
            <textarea className={s.bodyBox} value={body} aria-label="Email body"
                      onChange={(e) => setBody(e.target.value)} />
            {draft.context_used.length > 0 && (
              <p className={`${s.note} t-caption`}>Context used: {draft.context_used.join(' · ')}</p>
            )}
            {error && <p className={`${s.note} t-caption`} role="alert">{error}</p>}
            {draft.status === 'sent' && <p className={`${s.note} t-caption`}>This email has already been sent.</p>}
            <div className={s.actions}>
              <button type="button" className={`${s.btn} ${s.btnSend} t-label-md`}
                      disabled={busy || draft.status === 'sent'} onClick={send}>Send</button>
              <button type="button" className={`${s.btn} ${s.btnCancel} t-label-md`}
                      disabled={busy} onClick={onClose}>Cancel</button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
