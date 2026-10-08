import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Button, Chip, severityTone } from '@/components/primitives'
import { ApiError, ACTOR, api } from '@/api/client'
import type { Finding, Overview, TicketDetail } from '@/api/types'
import { DocumentPane } from './DocumentPane'
import { ResolveModal } from './ResolveModal'
import {
  actionsOf, clockTime, daysBetween, findingTag, kindLabel,
  longDate, newestOfKind, openFindings, requiredKinds, worstFinding,
  type VendorDocument, type VendorProposedAction, type VendorWithDocuments,
} from './vendorModel'
import s from './vendors.module.css'

/** Figma 176:2 — "Bumpin — Vendor detail".
 *
 *  Screen 176:8: back pill 176:29, title 176:32, then the document split —
 *  source document 176:33 (948x828) over the pages strip 176:74 (948x84) on the
 *  left, and the reading rail on the right (176:110 / 176:115 / 176:127, each
 *  316 wide) with a 24px gutter and 16px stacking.
 *
 *  This is the same document-split shape as the rider ticket detail. That file
 *  belongs to another agent, so the pieces are duplicated here rather than
 *  imported; see the report for the promotion candidates. */
export function VendorDetail() {
  const { vendorId } = useParams()
  const id = Number(vendorId)

  const [vendor, setVendor] = useState<VendorWithDocuments | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [ticket, setTicket] = useState<TicketDetail | null>(null)
  /* null until the operator picks one; the default is derived below. */
  const [docIndex, setDocIndex] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  /* The finding whose drafted reply is open; 204:237 borders only that card. */
  const [resolving, setResolving] = useState<number | null>(null)
  /* Which change-action row is mid-flight, and the refusal 202:3 prints under
     the row that caused it. Both are per-row, so the other rows stay usable. */
  const [actionBusy, setActionBusy] = useState<number | 'all' | null>(null)
  const [rowError, setRowError] = useState<{ index: number; message: string } | null>(null)

  const load = useCallback(async () => {
    const [ov, v] = await Promise.all([
      api.overview(),
      api.vendor(id) as Promise<VendorWithDocuments>,
    ])
    setOverview(ov)
    setVendor(v)
    setTicket(v.latest_ticket_id ? await api.ticket(v.latest_ticket_id) : null)
  }, [id])

  useEffect(() => {
    let live = true
    load().catch((e) => {
      if (live) setError(e instanceof Error ? e.message : 'Could not load this vendor.')
    })
    return () => { live = false }
  }, [load])

  const festivalEnd = overview?.festival.end_date ?? null
  const open = useMemo(() => openFindings(ticket), [ticket])

  /* One row of the change-actions card. Approving writes the schedule change
     and drafts one email; denying writes nothing at all. Neither sends, and
     neither decides the ticket, so a refusal only disables its own row. */
  const runRow = useCallback(async (index: number | 'all', call: () => Promise<unknown>) => {
    setActionBusy(index)
    setRowError(null)
    try {
      await call()
      await load()
    } catch (e) {
      const message = e instanceof ApiError
        ? (e.isAlreadyDecided ? `Already decided by ${e.decidedBy ?? 'someone else'}.` : e.detail)
        : 'That step did not go through.'
      /* Approve all applies in order and stops at the first refusal, so after a
         refetch the row still marked proposed is the one that failed. */
      const fresh = await api.ticket(ticket?.id ?? 0).catch(() => null)
      if (fresh) setTicket(fresh)
      const stuck = index === 'all'
        ? actionsOf(fresh).find((a) => a.status === 'proposed')?.index ?? 0
        : index
      setRowError({ index: stuck, message })
    } finally {
      setActionBusy(null)
    }
  }, [load, ticket?.id])

  if (error) {
    return (
      <>
        <BackLink />
        <p className={`${s.error} t-body-sm`}>{error}</p>
      </>
    )
  }
  if (!vendor || !festivalEnd) {
    return (
      <>
        <BackLink />
        <p className={`${s.loading} t-body-md`}>Opening the vendor…</p>
      </>
    )
  }

  const docs = vendor.documents
  const worst = worstFinding(open)
  /* Open on whichever document the worst open finding points at, else the first
     — the design's active page thumb is the second one, not the first (176:85). */
  const preferred = worst?.doc_id
    ? Math.max(0, docs.findIndex((d) => d.id === worst.doc_id))
    : 0
  const index = docIndex ?? preferred
  const active: VendorDocument | null = docs[index] ?? docs[0] ?? null

  const docFindings = open.filter((f) => active && f.doc_id === active.id)
  const noDocFindings = open.filter((f) => f.doc_id === null)
  /* What this page can show: what is drawn on the open document, plus findings
     with no document at all (ticket 6's missing gas certificate). */
  const shown = [...docFindings, ...noDocFindings]

  const conflicts = new Set(
    open.filter((f) => f.severity === 'conflict' && f.doc_id !== null).map((f) => f.doc_id!),
  )
  const draft = ticket?.draft_email ?? null

  /* The decision belongs to the ticket rather than to a phrase, so it hangs off
     the ticket's most significant open finding — conflict first, then warning
     (`worstFinding`). That finding is usually drawn on the open document, since
     the pane opens on the document it points at; when it is not (ticket 6 and
     ticket 9 both carry a `doc_id: null` conflict, and the operator can also page
     to a sibling document) it falls back to the worst finding this document CAN
     show, which the pane always gives an anchor — a box, a text mark, or a quote.
     A document with nothing flagged on it has no anchor at all and so carries no
     decision; the pane always lands on the flagged document first. */
  const anchor = worst && shown.some((f) => f.id === worst.id) ? worst : worstFinding(shown)
  const actions = actionsOf(ticket)

  /** The one card the anchor finding reveals. A change ticket turns it into the
   *  list of independently approvable steps (199:2); a document ticket keeps
   *  the single suggestion (176:65) and carries the vendor verdict in its
   *  footer. Either way it is ONE card, so the sentence is printed once. */
  const anchorCard = (f: Finding) =>
    ticket && actions.length > 0 ? (
      <ChangeActionsCard
        finding={f}
        actions={actions}
        busy={actionBusy}
        error={rowError}
        open={resolving === f.id}
        onApprove={(i) => runRow(i, () => api.approveAction(ticket.id, i))}
        onDeny={(i) => runRow(i, () => api.denyAction(ticket.id, i))}
        onApproveAll={() => runRow('all', () => api.approve(ticket.id))}
        onViewDraft={() => setResolving(f.id)}
      />
    ) : (
      <SuggestionCard
        finding={f}
        canResolve={Boolean(draft)}
        onResolve={() => setResolving(f.id)}
        onIgnore={async () => { if (ticket) setTicket(await api.ignoreFinding(ticket.id, f.id)) }}
        open={resolving === f.id}
        footer={ticket ? <VerdictFooter ticket={ticket} onChanged={load} /> : undefined}
      />
    )

  return (
    <>
      <BackLink />
      {/* 176:32 Vendor title — 48/54 */}
      <h1 className={`${s.detailTitle} t-display-lg`}>{vendor.name}</h1>

      <div className={s.split}>
        <div className={s.docColumn}>
          {/* 176:65 Bumpin suggestion — exactly one per open finding, each
              revealed from its own highlight, with the ticket's worst finding
              carrying the verdict too. Nothing sits under the document
              permanently: every card is reached from the thing it is about. */}
          <DocumentPane
            doc={active}
            findings={shown}
            /* Only the findings this document can actually show. The pane gives
               every finding it is handed an anchor, falling back to its quote
               when there is no box, so passing a finding that belongs to one of
               the vendor's OTHER documents would print that document's words
               under this one. */
            cards={shown.map((f) => ({
              findingId: f.id,
              node: f.id === anchor?.id ? anchorCard(f) : (
                <SuggestionCard
                  finding={f}
                  canResolve={Boolean(draft)}
                  onResolve={() => setResolving(f.id)}
                  onIgnore={async () => {
                    if (!ticket) return
                    setTicket(await api.ignoreFinding(ticket.id, f.id))
                  }}
                  open={resolving === f.id}
                />
              ),
            }))}
          />

          {/* 176:74 Pages — the design's five page thumbs. The API gives no page
              count for a PDF, so the strip steps through the vendor's documents. */}
          <div className={`${s.panel} ${s.panelFlush}`}>
            <div className={s.pages}>
              <button
                className={s.pagesNav}
                aria-label="Previous document"
                disabled={index <= 0}
                onClick={() => setDocIndex(Math.max(0, index - 1))}
              >
                <Chevron dir="left" />
              </button>
              <div className={s.pagesStrip}>
                {docs.map((d, i) => (
                  <button
                    key={d.id}
                    className={`${s.thumb} ${i === index ? s.thumbOn : ''}`}
                    aria-label={d.filename}
                    aria-current={i === index}
                    onClick={() => setDocIndex(i)}
                  >
                    {[22, 36, 30, 36, 30].map((w, k) => (
                      <span key={k} className={s.thumbLine} style={{ width: w }} />
                    ))}
                  </button>
                ))}
              </div>
              <button
                className={s.pagesNav}
                aria-label="Next document"
                disabled={index >= docs.length - 1}
                onClick={() => setDocIndex(Math.min(docs.length - 1, index + 1))}
              >
                <Chevron dir="right" />
              </button>
              <span className={`${s.pagesLabel} t-caption`}>
                Document {Math.min(index + 1, Math.max(docs.length, 1))} of {docs.length}
              </span>
            </div>
          </div>
        </div>

        <div className={s.rail}>
          {/* 176:110 Bumpin's reading */}
          <section className={`${s.panel} ${s.panelRail}`}>
            <h2 className={`${s.railTitle} t-heading-sm`}>Bumpin’s reading</h2>
            <div className={s.reading}>
              {readingLines(vendor, active, ticket, festivalEnd).map((line, i, all) => (
                <p key={i} className={`t-body-md ${i === all.length - 1 ? s.readingQuiet : ''}`}>
                  {line}
                </p>
              ))}
            </div>
          </section>

          {/* 176:115 Documents */}
          <section className={`${s.panel} ${s.panelDocuments}`}>
            <header className={s.docsHead}>
              <h2 className={`${s.docsHeadTitle} t-label-md`}>Documents</h2>
              <p className={`${s.docsHeadCount} t-label-sm`}>
                {docs.length} document{docs.length === 1 ? '' : 's'}
              </p>
            </header>
            <div className={s.donutRow}>
              <Donut total={docs.length} conflicts={conflicts.size} />
              <div className={s.legend}>
                <div className={s.legendRow}>
                  <span className={`${s.legendDot} ${s.legendDotConflict}`} aria-hidden />
                  <span className={`${s.legendLabel} t-body-sm`}>Conflicts</span>
                  <span className={`${s.legendValue} t-label-md`}>{conflicts.size}</span>
                </div>
                <div className={s.legendRow}>
                  <span className={`${s.legendDot} ${s.legendDotClear}`} aria-hidden />
                  <span className={`${s.legendLabel} t-body-sm`}>Clean</span>
                  <span className={`${s.legendValue} t-label-md`}>
                    {Math.max(0, docs.length - conflicts.size)}
                  </span>
                </div>
              </div>
            </div>
          </section>

          {/* 176:127 Details */}
          <section className={`${s.panel} ${s.panelDetails}`}>
            <h2 className={`${s.railTitle} t-label-md`}>Details</h2>
            <dl className={s.detailsTable}>
              <DetailRow label="Trading name" value={vendor.name} />
              <DetailRow label="Stall" value={vendor.site_zone} />
              <DetailRow label="Document" value={active ? active.filename : '—'} />
              <DetailRow label="Kind" value={active ? kindLabel(active.kind) : '—'} />
              <DetailRow label="Issuer" value={active?.issuer ?? '—'} />
              <DetailRow label="Received" value={longDate(active?.received_at ?? null)} />
              <DetailRow label="Expires" value={longDate(active?.expiry_date ?? null)} />
              <DetailRow
                label="Load-in"
                value={`${clockTime(vendor.load_in_start)}–${clockTime(vendor.load_in_end)} ${longDate(vendor.load_in_start)}`}
              />
              <DetailRow label="Gas on site" value={vendor.uses_gas ? 'Yes' : 'No'} />
              <DetailRow label="Contact" value={`${vendor.contact_name} · ${vendor.contact_email}`} />
              <DetailRow label="Status" value={vendor.status.replace(/_/g, ' ')} />
            </dl>
          </section>
        </div>
      </div>

      {resolving !== null && draft && (
        <ResolveModal
          draft={draft}
          cc={ACTOR}
          onClose={() => setResolving(null)}
          onSent={() => { setResolving(null); void load() }}
        />
      )}
    </>
  )
}

/* ------------------------------------------------------------------ pieces */

/** 176:29 Back — 175x36, r 18, #f2ecdc, chevron 5x10 at x 15. */
function BackLink() {
  return (
    <Link to="/vendors" className={`${s.back} t-label-md`}>
      <svg className={s.backIcon} viewBox="0 0 5 10" width="5" height="10" fill="none"
           stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
           aria-hidden>
        <path d="M 5 0 L 0 5 L 5 10" />
      </svg>
      Vendor progress
    </Link>
  )
}

/** 176:76 / 176:78 — 6x14, stroke 1.7, round caps. */
const Chevron = ({ dir }: { dir: 'left' | 'right' }) => (
  <svg viewBox="0 0 6 14" width="6" height="14" fill="none" stroke="currentColor"
       strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d={dir === 'left' ? 'M 6 0 L 0 7 L 6 14' : 'M 0 0 L 6 7 L 0 14'} />
  </svg>
)

const DetailRow = ({ label, value }: { label: string; value: string }) => (
  <div className={s.detailsRow}>
    <dt className="t-caption">{label}</dt>
    <dd className="t-label-sm" title={value}>{value}</dd>
  </div>
)

/** 176:118 / 176:119 — a 96x96 ring, innerRadius 0.62, segments separated by a
 *  0.07rad gap and starting at twelve o'clock plus half that gap. Exactly the
 *  arcData the two ellipses carry. */
function Donut({ total, conflicts }: { total: number; conflicts: number }) {
  const SIZE = 96
  const OUTER = SIZE / 2                     // 48
  const INNER = OUTER * 0.62                 // 29.76
  const R = (OUTER + INNER) / 2              // 38.88
  const W = OUTER - INNER                    // 18.24
  const GAP = 0.07
  const clean = Math.max(0, total - conflicts)

  const segments = [
    { value: conflicts, color: 'var(--accent-pink)' },
    { value: clean, color: 'var(--accent-green)' },
  ].filter((x) => x.value > 0)

  let cum = 0
  const arcs = segments.map((seg, i) => {
    const frac = seg.value / total
    const a0 = -Math.PI / 2 + cum * 2 * Math.PI + GAP / 2
    const sweep = frac * 2 * Math.PI - GAP
    cum += frac
    if (sweep <= 0) return null
    const a1 = a0 + sweep
    const p = (a: number) => `${(OUTER + R * Math.cos(a)).toFixed(3)} ${(OUTER + R * Math.sin(a)).toFixed(3)}`
    return (
      <path
        key={i}
        d={`M ${p(a0)} A ${R} ${R} 0 ${sweep > Math.PI ? 1 : 0} 1 ${p(a1)}`}
        fill="none"
        stroke={seg.color}
        strokeWidth={W}
      />
    )
  })

  return (
    <div className={s.donut}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img"
           aria-label={`${conflicts} of ${total} documents in conflict`}>
        {total === 0
          ? <circle cx={OUTER} cy={OUTER} r={R} fill="none" stroke="var(--ink-line)" strokeWidth={W} />
          : arcs}
      </svg>
      <span className={`${s.donutTotal} t-heading-lg`}>{total}</span>
    </div>
  )
}

/** 176:65 Bumpin suggestion — pad 18/20/24, tag 10px after the title, copy 10px
 *  under it, buttons 28px under that with a 10px gap.
 *
 *  `footer` carries the ticket verdict on the anchor finding. It used to be a
 *  second card stacked under this one, which printed the same sentence twice:
 *  a vendor ticket's summary IS its worst finding's message with the vendor
 *  name in front. The verdict belongs to the ticket rather than to the phrase,
 *  so it sits where 200:52 puts a list-wide action, in a quiet footer. */
function SuggestionCard({ finding, canResolve, onResolve, onIgnore, open, footer }: {
  finding: Finding
  canResolve: boolean
  onResolve: () => void
  onIgnore: () => Promise<void>
  open: boolean
  footer?: React.ReactNode
}) {
  const [busy, setBusy] = useState(false)
  return (
    <div className={`${s.suggestion} ${open ? s.suggestionOpen : ''}`}>
      <div className={s.suggestionHead}>
        <h3 className={`${s.suggestionTitle} t-label-md`}>Bumpin suggests</h3>
        <Chip tone={severityTone(finding.severity)}>{findingTag(finding.kind)}</Chip>
      </div>
      <p className={`${s.suggestionCopy} t-body-sm`}>
        {finding.message}{finding.suggestion ? ` ${finding.suggestion}` : ''}
      </p>
      <div className={s.suggestionActions}>
        <Button onClick={onResolve} disabled={!canResolve || busy}>Resolve</Button>
        <Button
          variant="outline"
          disabled={busy}
          onClick={async () => { setBusy(true); try { await onIgnore() } finally { setBusy(false) } }}
        >
          Ignore
        </Button>
      </div>
      {!canResolve && (
        <p className={`${s.notice} t-caption`}>No reply has been drafted for this ticket yet.</p>
      )}
      {footer}
    </div>
  )
}

/** The verdict on the whole vendor, in the footer of the suggestion above it.
 *
 *  Approving clears the vendor (`vendors.status` becomes `completed`);
 *  rejecting marks them rejected and leaves the drafted reply as a draft.
 *  Neither sends. Approving over an open conflict is refused by the backend,
 *  and that refusal turns into the override field rather than a dead end. */
function VerdictFooter({ ticket, onChanged }: {
  ticket: TicketDetail
  onChanged: () => Promise<void>
}) {
  const [mode, setMode] = useState<'idle' | 'reject' | 'override'>('idle')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const decided = Boolean(ticket.decided_by)

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      setMode('idle')
      setReason('')
      await onChanged()
    } catch (e) {
      if (e instanceof ApiError && e.isAlreadyDecided) {
        setError(`Already decided by ${e.decidedBy} at ${e.decidedAt}.`)
        await onChanged()
      } else if (e instanceof ApiError && e.isBlockedByConflict) {
        setError(`${e.detail} Approve anyway with a reason.`)
        setMode('override')
      } else {
        setError(e instanceof Error ? e.message : 'That did not go through.')
      }
    } finally {
      setBusy(false)
    }
  }

  if (decided) {
    return (
      <p className={`${s.notice} t-caption`}>
        {ticket.status.replace(/_/g, ' ')} by {ticket.decided_by} at {ticket.decided_at}.
      </p>
    )
  }

  return (
    <>
      {error && <p className={`${s.notice} t-caption`}>{error}</p>}
      {mode !== 'idle' && (
        <label className={s.field} style={{ borderTop: 0, padding: '14px 0 0' }}>
          <span className={`${s.fieldLabel} t-label-sm`}>
            {mode === 'reject' ? 'Reason' : 'Override'}
          </span>
          <input
            className={s.fieldInput}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={mode === 'reject' ? 'Why this is rejected' : 'Why this is approved anyway'}
          />
        </label>
      )}
      <div className={s.cardFoot}>
        {mode === 'idle' ? (
          <>
            <button type="button" className={`${s.textAction} t-label-md`} disabled={busy}
                    onClick={() => run(() => api.approve(ticket.id))}>
              Approve vendor
            </button>
            <button type="button" className={`${s.textAction} t-label-md`} disabled={busy}
                    onClick={() => setMode('reject')}>
              Reject vendor
            </button>
          </>
        ) : (
          <>
            <button type="button" className={`${s.textAction} t-label-md`}
                    disabled={busy || reason.trim().length === 0}
                    onClick={() => run(() =>
                      mode === 'reject'
                        ? api.reject(ticket.id, reason.trim())
                        : api.approve(ticket.id, reason.trim()))}>
              {mode === 'reject' ? 'Confirm reject' : 'Approve anyway'}
            </button>
            <button type="button" className={`${s.textAction} t-label-md`} disabled={busy}
                    onClick={() => { setMode('idle'); setReason('') }}>
              Cancel
            </button>
          </>
        )}
      </div>
    </>
  )
}

/** 199:2 "Card — Change actions", states 200:3 / 201:3 / 202:3.
 *
 *  Same 440-wide shell as the suggestion, with the single paragraph replaced by
 *  a list of steps that are each approved or turned down on their own.
 *  Approving a `move_load_in` row writes the new window straight into
 *  `vendors.load_in_*` and drafts one confirmation; approving a `notify` row
 *  only drafts. Denying writes nothing anywhere. Nothing sends.
 *
 *  203:15 draws an Edit popover and the per-row second button is Edit. A vendor
 *  load-in change is one time that the vendor themselves asked for, so there is
 *  nothing for Ravi to retime; the useful second verdict is no. The button
 *  keeps 200:19's geometry and calls `denyAction`. */
function ChangeActionsCard({
  finding, actions, busy, error, open, onApprove, onDeny, onApproveAll, onViewDraft,
}: {
  finding: Finding
  actions: VendorProposedAction[]
  busy: number | 'all' | null
  error: { index: number; message: string } | null
  open: boolean
  onApprove: (index: number) => void
  onDeny: (index: number) => void
  onApproveAll: () => void
  onViewDraft: () => void
}) {
  const anyProposed = actions.some((a) => a.status === 'proposed')
  const n = actions.length

  return (
    <div className={`${s.suggestion} ${s.listCard} ${open ? s.suggestionOpen : ''}`}>
      <div className={s.listIntro}>
        <div className={s.suggestionHead}>
          <h3 className={`${s.suggestionTitle} t-label-md`}>Bumpin suggests</h3>
          {/* 200:7 reads "Change"; the vendor slice names the finding kind, so
              this tag says Load-in like every other card on the screen. */}
          <Chip tone={severityTone(finding.severity)}>{findingTag(finding.kind)}</Chip>
        </div>
        <p className={`${s.listIntroCopy} t-body-sm`}>
          {finding.message} {n} {n === 1 ? 'step' : 'steps'}, each approved on its own.
        </p>
      </div>

      <div className={s.rows}>
        <div className={s.divider} aria-hidden />
        {actions.map((a) => {
          const done = a.status !== 'proposed'
          const failed = error?.index === a.index
          return (
            <div key={a.index}>
              <div className={`${s.row} ${failed ? s.rowBlocked : ''}`}>
                <div className={s.rowCopy}>
                  <p className={`${s.rowTitle} ${done ? s.rowTitleDone : ''} t-label-md`}>{a.title}</p>
                  <p className={`${s.rowDetail} t-caption`}>{a.detail}</p>
                  {failed && <p className={`${s.rowError} t-caption`} role="alert">{error.message}</p>}
                </div>

                {done ? (
                  <div className={s.rowStatus}>
                    <span className={`${s.rowDecidedBy} t-label-sm`}>
                      {a.status === 'denied' ? 'Denied' : 'Approved'} by {a.approved_by ?? 'someone'}
                    </span>
                    {a.outbox_id !== null && (
                      <button type="button" className={`${s.textAction} ${s.textActionQuiet} t-label-sm`}
                              onClick={onViewDraft}>
                        View draft
                      </button>
                    )}
                  </div>
                ) : (
                  <div className={s.rowActions}>
                    {/* 202:3 makes the refused row's Approve the outline one, so
                        the primary press is no longer the one that just failed. */}
                    <button type="button"
                            className={`${s.pill} ${failed ? s.pillOutline : s.pillFilled} t-label-sm`}
                            disabled={busy !== null} onClick={() => onApprove(a.index)}>
                      Approve
                    </button>
                    <button type="button" className={`${s.pill} ${s.pillOutline} t-label-sm`}
                            disabled={busy !== null} onClick={() => onDeny(a.index)}>
                      Deny
                    </button>
                  </div>
                )}
              </div>
              <div className={s.divider} aria-hidden />
            </div>
          )
        })}
      </div>

      <div className={s.cardFoot}>
        <button type="button" className={`${s.textAction} t-label-md`}
                disabled={!anyProposed || busy !== null} onClick={onApproveAll}>
          Approve all
        </button>
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- copy ---- */

/** What the right rail says when there is no ticket to quote. */
function readingLines(
  vendor: VendorWithDocuments,
  active: VendorDocument | null,
  ticket: TicketDetail | null,
  festivalEnd: string,
): string[] {
  const docs = vendor.documents
  const parsed = docs.filter((d) => d.expiry_date && d.issuer).length
  const first = `${docs.length} document${docs.length === 1 ? '' : 's'} on file. `
    + `${parsed} parsed with both an issuer and an expiry date.`

  const worst = worstFinding(openFindings(ticket))
  let second: string
  if (worst) {
    second = worst.message
  } else if (active?.expiry_date) {
    const days = daysBetween(festivalEnd, active.expiry_date)
    second = days >= 0
      ? `${kindLabel(active.kind)} runs to ${longDate(active.expiry_date)}, ${days} day${days === 1 ? '' : 's'} past the ${longDate(festivalEnd)} close.`
      : `${kindLabel(active.kind)} lapses ${longDate(active.expiry_date)}, ${-days} day${days === -1 ? '' : 's'} before the festival ends.`
  } else {
    second = 'No expiry date could be read off the selected document.'
  }

  return [first, second, requirementSummary(vendor, festivalEnd)]
}

function requirementSummary(vendor: VendorWithDocuments, festivalEnd: string) {
  const required = requiredKinds(vendor)
  const missing = required.filter((k) => !newestOfKind(vendor.documents, k))
  const expiring = required
    .map((k) => newestOfKind(vendor.documents, k))
    .filter((d): d is VendorDocument => Boolean(d) && (!d!.expiry_date || d!.expiry_date < festivalEnd))

  if (missing.length === 0 && expiring.length === 0) {
    return `All ${required.length} required document${required.length === 1 ? '' : 's'} for a ${vendor.type} vendor are on file and valid through ${longDate(festivalEnd)}.`
  }
  const parts: string[] = []
  if (missing.length) parts.push(`${missing.map(kindLabel).join(', ')} not on file`)
  if (expiring.length) parts.push(`${expiring.map((d) => kindLabel(d.kind)).join(', ')} does not cover event day`)
  return `${parts.join('; ')}.`
}
