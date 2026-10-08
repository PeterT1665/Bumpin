import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '@/api/client'
import type { Finding, Notification, OutboxRow, PhoneCard, TicketDetail } from '@/api/types'
import s from './phone.module.css'

/* Ravi's phone. He is never at a desk during the festival, so this is the whole
   product for him: one list of things that need a decision, most urgent first,
   each one approvable without opening the laptop app. Polls like the rest of the
   app, so a card for a new email appears on its own. */

const POLL_MS = 2500

const REASON_LABEL: Record<PhoneCard['reason'], string> = {
  major_change: 'Major change',
  needs_review: 'Needs review',
  pending_approval: 'Ready to approve',
}

const FINDING_LABEL: Partial<Record<Finding['kind'], string>> = {
  shortage: 'Shortage',
  double_booking: 'Double booking',
  over_budget: 'Over budget',
  expired_cert: 'Expires too early',
  missing_doc: 'Missing document',
  low_confidence: 'Not sure',
  schedule_change: 'Schedule change',
  low_capacity: 'Low capacity',
}

const cap = (name?: string | null) => (name ? name[0].toUpperCase() + name.slice(1) : '')

function when(iso: string) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  // Recent items read as relative, so a card that just arrived says "Just now"
  // rather than a calendar date next to the demo's November mail.
  const mins = Math.round((Date.now() - d.getTime()) / 60000)
  if (mins >= -5 && mins < 1) return 'Just now'
  if (mins >= 1 && mins < 60) return `${mins} min ago`
  if (mins >= 60 && mins < 12 * 60) return `${Math.round(mins / 60)} h ago`
  return d.toLocaleString('en-AU', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function errorText(e: unknown) {
  if (e instanceof ApiError) {
    if (e.isAlreadyDecided) return `Already decided by ${cap(e.decidedBy)} at ${when(e.decidedAt ?? '')}.`
    return e.detail
  }
  return 'Something went wrong. Try again.'
}

export function Phone() {
  const [cards, setCards] = useState<PhoneCard[] | null>(null)
  const [notes, setNotes] = useState<Notification[]>([])
  const [offline, setOffline] = useState(false)
  const [openId, setOpenId] = useState<number | null>(null)
  // The open card stays on screen after it is decided and drops out of the
  // feed, so the emails it drafted can still be read and sent from here.
  const [held, setHeld] = useState<PhoneCard | null>(null)
  const [fresh, setFresh] = useState<Set<string>>(new Set())
  const [banner, setBanner] = useState<PhoneCard | null>(null)
  const [showNotes, setShowNotes] = useState(false)
  const known = useRef<Set<string> | null>(null)

  const load = useCallback(async () => {
    try {
      const [c, n] = await Promise.all([api.phoneCards(), api.notifications(true)])
      if (known.current) {
        const added = c.filter((x) => !known.current!.has(x.id))
        if (added.length) {
          setFresh((prev) => new Set([...prev, ...added.map((a) => a.id)]))
          setBanner(added[0])
          navigator.vibrate?.(200)
        }
      }
      known.current = new Set(c.map((x) => x.id))
      setCards(c)
      setNotes(n)
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  useEffect(() => {
    void load()
    const t = window.setInterval(() => void load(), POLL_MS)
    return () => window.clearInterval(t)
  }, [load])

  useEffect(() => {
    if (!banner) return
    const t = window.setTimeout(() => setBanner(null), 6000)
    return () => window.clearTimeout(t)
  }, [banner])

  const open = (c: PhoneCard) => {
    const closing = openId === c.ticket_id
    setOpenId(closing ? null : c.ticket_id)
    setHeld(closing ? null : c)
    setFresh((prev) => { const n = new Set(prev); n.delete(c.id); return n })
    setBanner(null)
  }

  const markAllSeen = async () => {
    await Promise.all(notes.map((n) => api.markSeen(n.id).catch(() => undefined)))
    setShowNotes(false)
    void load()
  }

  const urgent = cards?.filter((c) => c.urgency === 'high').length ?? 0
  const handled = held && cards && !cards.some((c) => c.id === held.id) ? held : null
  const shown = cards && handled ? [handled, ...cards] : cards

  return (
    <div className={s.stage}>
      <div className={s.phone}>
        <header className={s.top}>
          <div>
            <p className={`${s.brand} t-overline`}>Bumpin</p>
            <h1 className={`${s.hello} t-heading-lg`}>Hi Ravi</h1>
            <p className={`${s.sub} t-body-sm`}>
              {cards === null ? 'Loading…'
                : cards.length === 0 ? 'Nothing needs you right now.'
                : `${cards.length} need${cards.length === 1 ? 's' : ''} you${urgent ? `, ${urgent} urgent` : ''}`}
            </p>
          </div>
          <button type="button" className={s.bell} aria-label={`${notes.length} new notifications`}
                  onClick={() => setShowNotes(!showNotes)}>
            <BellIcon />
            {notes.length > 0 && <span className={`${s.badge} t-label-sm`}>{notes.length}</span>}
          </button>
        </header>

        {showNotes && (
          <section className={s.notes}>
            {notes.length === 0
              ? <p className="t-body-sm">No new notifications.</p>
              : notes.map((n) => <p key={n.id} className={`${s.note} t-body-sm`}>{n.text}</p>)}
            {notes.length > 0 && (
              <button type="button" className={`${s.link} t-label-md`} onClick={markAllSeen}>Mark all as read</button>
            )}
          </section>
        )}

        {banner && (
          <button type="button" className={s.banner} onClick={() => open(banner)}>
            <span className={`${s.bannerTag} t-overline`}>New</span>
            <span className="t-label-md">{banner.title}</span>
          </button>
        )}

        {offline && <p className={`${s.offline} t-body-sm`}>Can't reach Bumpin. Retrying…</p>}

        <main className={s.list}>
          {shown?.map((c) => (
            <article key={c.id}
                     className={`${s.card} ${c === handled ? s.handled : s[`u_${c.urgency}`]} ${fresh.has(c.id) ? s.fresh : ''}`}>
              <button type="button" className={s.cardHead} onClick={() => open(c)} aria-expanded={openId === c.ticket_id}>
                <span className={s.chips}>
                  <span className={`${s.chip} t-label-sm`}>{c === handled ? 'Handled' : REASON_LABEL[c.reason]}</span>
                  {fresh.has(c.id) && <span className={`${s.chip} ${s.chipNew} t-label-sm`}>New</span>}
                  <span className={`${s.time} t-caption`}>{when(c.created_at)}</span>
                </span>
                <span className={`${s.title} t-heading-sm`}>{c.title}</span>
                <span className={`${s.summary} t-body-sm`}>{c.summary}</span>
                {c.snippet && <span className={`${s.snippet} t-body-sm`}>“{c.snippet}”</span>}
              </button>
              {openId === c.ticket_id && <CardDetail ticketId={c.ticket_id} onChanged={load} />}
            </article>
          ))}
          {cards?.length === 0 && (
            <div className={s.empty}>
              <p className="t-heading-sm">All clear</p>
              <p className="t-body-sm">New emails that need a decision will appear here.</p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

function CardDetail({ ticketId, onChanged }: { ticketId: number; onChanged: () => void }) {
  const [t, setT] = useState<TicketDetail | null>(null)
  const [drafts, setDrafts] = useState<OutboxRow[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [readId, setReadId] = useState<number | null>(null)

  const refresh = useCallback(async () => {
    const [d, o] = await Promise.all([api.ticket(ticketId), api.outbox({ ticket_id: ticketId })])
    setT(d)
    setDrafts(o)
  }, [ticketId])

  useEffect(() => { void refresh() }, [refresh])

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key)
    setMsg(null)
    try {
      await fn()
      await refresh()
      onChanged()
    } catch (e) {
      setMsg(errorText(e))
      await refresh().catch(() => undefined)
    } finally {
      setBusy(null)
    }
  }

  if (!t) return <div className={s.detail}><p className="t-body-sm">Loading…</p></div>

  const actions = t.proposed_actions ?? []
  const findings = t.findings.filter((f) => f.status === 'open' && f.kind !== 'parsed_field' && f.severity !== 'info')
  const decidable = t.type !== 'help' && !t.decided_by
  const laptopHref = t.owner_type === 'vendor' ? `/vendors/${t.owner_id}` : `/tickets/${t.id}`
  const pendingDrafts = drafts.filter((d) => d.status === 'draft')
  const sent = drafts.filter((d) => d.status === 'sent')

  return (
    <div className={s.detail}>
      {actions.length > 0 && (
        <section className={s.block}>
          <p className={`${s.blockTitle} t-overline`}>Bumpin proposes</p>
          {actions.map((a) => (
            <div key={a.index} className={s.step}>
              <p className="t-body-md-b">{a.title}</p>
              <p className={`${s.muted} t-body-sm`}>{a.detail}</p>
              {a.status === 'proposed' ? (
                <div className={s.row}>
                  <button type="button" className={`${s.btn} ${s.btnFill} t-label-md`} disabled={busy !== null}
                          onClick={() => run(`a${a.index}`, () => api.approveAction(t.id, a.index))}>
                    {busy === `a${a.index}` ? 'Approving…' : 'Approve'}
                  </button>
                  <button type="button" className={`${s.btn} t-label-md`} disabled={busy !== null}
                          onClick={() => run(`d${a.index}`, () => api.denyAction(t.id, a.index))}>Deny</button>
                </div>
              ) : (
                <p className={`${s.done} t-label-sm`}>
                  {a.status === 'approved' ? 'Approved' : 'Denied'} by {cap(a.approved_by)}
                  {a.status === 'approved' && a.outbox_id ? ', email drafted' : ''}
                </p>
              )}
            </div>
          ))}
          {actions.some((a) => a.status === 'proposed') && (
            <button type="button" className={`${s.btn} ${s.btnFill} ${s.wide} t-label-md`} disabled={busy !== null}
                    onClick={() => run('all', () => api.approve(t.id))}>
              {busy === 'all' ? 'Approving…' : 'Approve all'}
            </button>
          )}
        </section>
      )}

      {actions.length === 0 && findings.length > 0 && (
        <section className={s.block}>
          <p className={`${s.blockTitle} t-overline`}>What Bumpin found</p>
          {findings.map((f) => (
            <div key={f.id} className={`${s.step} ${f.severity === 'conflict' ? s.conflict : s.warning}`}>
              <p className={`${s.kind} t-label-sm`}>{FINDING_LABEL[f.kind] ?? 'Check'}</p>
              <p className="t-body-md">{f.message}</p>
              {f.suggestion && <p className={`${s.muted} t-body-sm`}>{f.suggestion}</p>}
              <div className={s.row}>
                {f.kind !== 'low_confidence' && (
                  <button type="button" className={`${s.btn} ${s.btnFill} t-label-md`} disabled={busy !== null}
                          onClick={() => run(`r${f.id}`, () => api.resolveFinding(t.id, f.id))}>
                    {busy === `r${f.id}` ? 'Drafting…' : 'Resolve'}
                  </button>
                )}
                <button type="button" className={`${s.btn} t-label-md`} disabled={busy !== null}
                        onClick={() => run(`i${f.id}`, () => api.ignoreFinding(t.id, f.id))}>
                  {f.kind === 'low_confidence' ? 'Dismiss' : 'Ignore'}
                </button>
              </div>
            </div>
          ))}
        </section>
      )}

      {pendingDrafts.length > 0 && (
        <section className={s.block}>
          <p className={`${s.blockTitle} t-overline`}>Drafted, waiting for you to send</p>
          {pendingDrafts.map((d) => (
            <div key={d.id} className={s.draft}>
              <button type="button" className={s.draftHead} onClick={() => setReadId(readId === d.id ? null : d.id)}>
                <span className="t-label-md">{d.subject}</span>
                <span className={`${s.muted} t-caption`}>To {d.to_addr}</span>
              </button>
              {readId === d.id && <pre className={`${s.body} t-body-sm`}>{d.body}</pre>}
              <button type="button" className={`${s.btn} ${s.btnFill} t-label-md`} disabled={busy !== null}
                      onClick={() => run(`s${d.id}`, () => api.send(d.id))}>
                {busy === `s${d.id}` ? 'Sending…' : 'Send'}
              </button>
            </div>
          ))}
        </section>
      )}
      {sent.length > 0 && (
        <p className={`${s.done} t-label-sm`}>{sent.length} email{sent.length === 1 ? '' : 's'} sent</p>
      )}

      {decidable && (
        <section className={s.block}>
          {!rejecting ? (
            <div className={s.row}>
              <button type="button" className={`${s.btn} ${s.btnFill} t-label-md`} disabled={busy !== null}
                      onClick={() => run('approve', () => api.approve(t.id))}>
                {busy === 'approve' ? 'Approving…' : t.type === 'rider_needs' ? 'Approve rider' : 'Approve vendor'}
              </button>
              <button type="button" className={`${s.btn} t-label-md`} disabled={busy !== null}
                      onClick={() => setRejecting(true)}>Reject</button>
            </div>
          ) : (
            <div className={s.reject}>
              <textarea className={`${s.input} t-body-sm`} rows={3} value={reason} placeholder="Why this is rejected"
                        onChange={(e) => setReason(e.target.value)} aria-label="Reason for rejecting" />
              <div className={s.row}>
                <button type="button" className={`${s.btn} ${s.btnFill} t-label-md`}
                        disabled={busy !== null || !reason.trim()}
                        onClick={() => run('reject', () => api.reject(t.id, reason.trim())).then(() => setRejecting(false))}>
                  Confirm reject
                </button>
                <button type="button" className={`${s.btn} t-label-md`} onClick={() => setRejecting(false)}>Cancel</button>
              </div>
            </div>
          )}
        </section>
      )}
      {t.decided_by && (
        <p className={`${s.done} t-label-sm`}>{cap(t.status)} by {cap(t.decided_by)}</p>
      )}

      {msg && <p className={`${s.error} t-body-sm`} role="alert">{msg}</p>}
      <Link className={`${s.link} t-label-md`} to={laptopHref}>Open full ticket</Link>
    </div>
  )
}

function BellIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  )
}
