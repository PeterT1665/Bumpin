import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '@/api/client'
import type { Artist, DocumentRef, Finding, Highlight, TicketDetail as Ticket } from '@/api/types'
import { DocumentPane, docKindOf, useDocumentText } from './DocumentPane'
import { ChangeActionsCard, FindingCard, type RowError } from './cards'
import { ResolveModal } from './ResolveModal'
import { DetailsPanel, DonutPanel, ReadingPanel, type DetailRow } from './rail'
import { DecisionPanel } from './DecisionPanel'
import { djNovaReading, isDjNova, patchHighlights, patchTicket } from './djNova'
import { hhmm, kindLabel, setTime } from './riders'

/** "dj_nova_rider_handwritten.png" -> "PNG". What the pane is about to draw. */
const fileType = (filename: string) =>
  (filename.split('.').pop() ?? '').toUpperCase() || 'FILE'
import s from './TicketDetail.module.css'

/* One route, two layouts. `rider_needs` is Figma 118:2 — a document with the
 * parsed claims highlighted in place. `help` is Figma 230:2 — the same frame
 * with the email body as plain text, the suggestion card replaced by a list of
 * independently approvable actions, and the donut reading Steps.
 *
 * Both cards anchor the same way: no card sits outside a highlight. Hover the
 * claim and the card appears beside it, the way Grammarly's does. The help card
 * carries Approve buttons and an edit form with text inputs, which a card that
 * vanished on pointer-out could not be used for, so clicking the highlight pins
 * it open until Escape or a click outside — see DocumentPane. A ticket whose
 * highlight is missing falls back to the card in the flow rather than losing it. */

const POLL_MS = 3000

export function TicketDetail() {
  const { ticketId } = useParams()
  const id = Number(ticketId)

  const [ticket, setTicketRaw] = useState<Ticket | null>(null)
  const [artist, setArtist] = useState<Artist | null>(null)
  const [rawHighlights, setHighlights] = useState<Highlight[]>([])

  /* Dj Nova's ticket is scripted for the demo — see djNova.ts. Every path that
     writes the ticket goes through the patch, not just the first load, or
     resolving one finding would hand the screen back the unscripted copy. */
  const setTicket = useCallback((t: Ticket) => setTicketRaw(patchTicket(t)), [])
  const [loadError, setLoadError] = useState<string | null>(null)

  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<number | null>(null)
  const [rowError, setRowError] = useState<RowError | null>(null)
  const [busy, setBusy] = useState<number | 'all' | null>(null)
  const [findingBusy, setFindingBusy] = useState(false)
  const [resolving, setResolving] = useState(false)
  const [resolveError, setResolveError] = useState<string | null>(null)
  const [resolveNote, setResolveNote] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!Number.isFinite(id)) { setLoadError('Unknown ticket'); return }
    try {
      const t = await api.ticket(id)
      setTicket(t)
      setLoadError(null)
      if (t.owner.type === 'artist') {
        const all = await api.artists()
        setArtist(all.find((a) => a.id === t.owner.id) ?? null)
      }
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Could not load the ticket')
    }
  }, [id])

  /* Poll, but never while a dialog is open — a refetch mid-edit would reseed it. */
  useEffect(() => {
    let alive = true
    const tick = () => { if (alive && !modalOpen) void load() }
    tick()
    const h = window.setInterval(tick, POLL_MS)
    return () => { alive = false; window.clearInterval(h) }
  }, [load, modalOpen])

  /* Which document the pane is showing. A ticket can carry more than one —
     Dj Nova sent a handwritten page AND a typed addendum, and a conflict sits
     on each — so showing only the first put a conflict on the progress bar
     with nothing on screen behind it. `null` means "whichever the first
     finding points at", so the pane still opens on the flagged page. */
  const [pickedDoc, setPickedDoc] = useState<number | null>(null)

  const doc: DocumentRef | null = useMemo(() => {
    if (!ticket) return null
    if (pickedDoc !== null) {
      const chosen = ticket.documents.find((d) => d.id === pickedDoc)
      if (chosen) return chosen
    }
    const withBox = ticket.findings.find((f) => f.doc_id !== null)
    if (withBox) {
      const hit = ticket.documents.find((d) => d.id === withBox.doc_id)
      if (hit) return hit
    }
    return ticket.documents[0] ?? null
  }, [ticket, pickedDoc])

  useEffect(() => {
    if (!doc) { setHighlights([]); return }
    let alive = true
    api.highlights(doc.id)
      .then((h) => { if (alive) setHighlights(h) })
      .catch(() => { if (alive) setHighlights([]) })
    return () => { alive = false }
  }, [doc?.id, ticket?.updated_at])

  /* The scripted boxes are applied here rather than on the way in, so they
     survive a refetch of either the ticket or the document. */
  const highlights = useMemo(
    () => patchHighlights(ticket, rawHighlights), [ticket, rawHighlights])

  const kind = useMemo(() => docKindOf(highlights, doc?.filename), [highlights, doc?.filename])

  /* 118:2 opens on page 2 of 5 — the page the finding is on, not page 1. */
  useEffect(() => {
    const first = highlights.find((h) => h.status === 'open')
    if (first) setPage(first.page)
  }, [doc?.id, highlights])
  const text = useDocumentText(doc?.id ?? null, kind)

  /* Every finding can be selected, decided ones included: their highlights are
     still drawn and still clickable, so clicking one has to put its card up.
     The DEFAULT still prefers an open conflict — that is the work outstanding,
     and landing on a finished one would hide it. */
  const findings = ticket?.findings ?? []
  const openFindings = useMemo(
    () => findings.filter((f) => f.status === 'open'),
    [ticket],
  )
  useEffect(() => {
    if (selected !== null && findings.some((f) => f.id === selected)) return
    const first = openFindings.find((f) => f.severity === 'conflict')
      ?? openFindings[0] ?? findings[0]
    if (first) setSelected(first.id)
    else if (selected !== null) setSelected(null)
  }, [openFindings, selected])

  const selectedFinding: Finding | null =
    findings.find((f) => f.id === selected) ?? null

  /* "If a finding has no box, show the quote as text instead." */

  /* ---- finding actions (rider tickets) ---- */

  const ignoreFinding = async (findingId: number) => {
    setFindingBusy(true)
    try { setTicket(await api.ignoreFinding(id, findingId)) }
    catch (e) { setLoadError(e instanceof ApiError ? e.detail : 'Could not update the finding') }
    finally { setFindingBusy(false) }
  }

  /** A rider ticket carries no draft until this call runs: the resolve POST is
   *  what marks the finding resolved AND writes the reply into the outbox, so the
   *  panel can only open on what comes back. It drafts for `shortage`,
   *  `double_booking` and `over_budget` and stays quiet for every other kind, so
   *  a new outbox id is the test rather than a copy of the backend's list. */
  const resolveRef = useRef(false)
  const startResolve = async (findingId: number) => {
    if (resolveRef.current) return            // a double click must not draft twice
    resolveRef.current = true
    setResolving(true)
    setResolveError(null)
    setResolveNote(null)
    setSendError(null)
    const before = ticket?.draft_email?.outbox_id ?? null
    try {
      const fresh = await api.resolveFinding(id, findingId)
      setTicket(fresh)
      if (fresh.draft_email && fresh.draft_email.outbox_id !== before) setModalOpen(true)
      else setResolveNote('Finding resolved. Bumpin does not draft a reply for this kind.')
    } catch (e) {
      setResolveError(e instanceof ApiError ? e.detail : 'Could not resolve the finding')
    } finally {
      resolveRef.current = false
      setResolving(false)
    }
  }

  const sendDraft = async (edits: { subject?: string; body?: string }) => {
    const draft = ticket?.draft_email
    if (!draft) return
    setFindingBusy(true)
    setSendError(null)
    try {
      if (edits.subject !== undefined || edits.body !== undefined) {
        await api.updateDraft(draft.outbox_id, edits)
      }
      await api.send(draft.outbox_id)
      setModalOpen(false)
      /* The finding was resolved before the panel opened, so this only picks the
         outbox row's new `sent` status back up. */
      await load()
    } catch (e) {
      setSendError(e instanceof ApiError ? e.detail : 'Could not send the draft')
    } finally {
      setFindingBusy(false)
    }
  }

  /* ---- proposed-action actions (help tickets) ---- */

  /** Approving one action writes the schedule change immediately and drafts one
   *  email. It does not send. The ticket goes `in_progress` after the first
   *  approve and only `resolved` once every action is approved, so the list
   *  stays mixed in between. */
  const approveAction = async (index: number) => {
    setBusy(index)
    setRowError(null)
    try {
      setTicket(await api.approveAction(id, index))
    } catch (e) {
      if (e instanceof ApiError) {
        /* Two different refusals. `isAlreadyDecided` is a 409 carrying
           decided_by; a conflict refusal carries only `detail` — and the
           overlap message in particular reaches the client as 400, because
           shared/tickets.py maps the handler's ValueError to 400. Treat any
           non-decided refusal as the inline row error and point at Edit. */
        setRowError({
          index,
          message: e.isAlreadyDecided
            ? `Already decided by ${e.decidedBy ?? 'someone else'}.`
            : e.detail,
        })
      } else {
        setRowError({ index, message: 'Could not approve that step.' })
      }
      await load()
    } finally {
      setBusy(null)
    }
  }

  const approveAll = async () => {
    setBusy('all')
    setRowError(null)
    try {
      setTicket(await api.approve(id))
    } catch (e) {
      const message = e instanceof ApiError ? e.detail : 'Could not approve every step.'
      /* Actions apply in order and stop at the first refusal, so the row still
         marked `proposed` after a refetch is the one that failed. */
      const fresh = await api.ticket(id).catch(() => null)
      if (fresh) setTicket(fresh)
      const stuck = (fresh?.proposed_actions ?? []).find((a) => a.status === 'proposed')
      setRowError({ index: stuck?.index ?? 0, message })
    } finally {
      setBusy(null)
    }
  }

  /** The quiet half of the pair. Denying writes nothing to the run sheet and
   *  drafts no email — it only closes the action, and the ticket resolves once
   *  every action has been decided one way or the other. */
  const denyAction = async (index: number) => {
    setBusy(index)
    setRowError(null)
    try { setTicket(await api.denyAction(id, index)) }
    catch (e) {
      setRowError({
        index,
        message: e instanceof ApiError
          ? (e.isAlreadyDecided ? `Already decided by ${e.decidedBy ?? 'someone else'}.` : e.detail)
          : 'Could not turn that step down.',
      })
      await load()
    } finally { setBusy(null) }
  }

  if (loadError) return <Shell><p className={`${s.state} t-body-md`}>{loadError}</p></Shell>
  if (!ticket) return <Shell><p className={`${s.state} t-body-md`}>Loading the ticket…</p></Shell>

  const isHelp = ticket.type === 'help'
  const actions = ticket.proposed_actions ?? []
  const stage = artist?.stage_name ?? null

  /* ---- the reading rail ---- */

  /* A conflict is a requirement in dispute. Warnings are not conflicts, which
     is the same rule the board's progress bar counts by. */
  const conflictCount = ticket.findings.filter((f) => f.severity === 'conflict').length
  /* Falls back to the findings only when no rider was parsed, so the chart is
     never emptier than the truth. */
  const requirementCount = ticket.requirements?.total ?? ticket.findings.length
  const approved = actions.filter((a) => a.status === 'approved').length
  const proposed = actions.filter((a) => a.status === 'proposed').length
  const firstMove = actions.find((a) => a.kind === 'move_set')

  /* Three sentences, in the order an operator asks the questions: what did
     they ask for, what is wrong with it, and can we cover it. The second is
     the highlights in words — the same conflicts that are boxed on the page. */
  const req = ticket.requirements
  const conflictLines = ticket.findings.filter((f) => f.severity === 'conflict')
  const shortfall = requirementCount > 0 ? conflictCount / requirementCount : 0
  const coverage =
    conflictCount === 0 ? 'Everything on this rider is covered by what the venue owns.'
      : shortfall <= 0.15 ? `Inventory covers nearly all of this rider: ${conflictCount} of ${requirementCount} requirements fall short.`
      : shortfall <= 0.35 ? `Inventory is mostly sufficient: ${conflictCount} of ${requirementCount} requirements fall short.`
      : shortfall <= 0.6 ? `Inventory covers about half of this rider: ${conflictCount} of ${requirementCount} requirements fall short.`
      : `Inventory falls short on most of this rider: ${conflictCount} of ${requirementCount} requirements.`

  /* Composed off the artist so the sentence and the rail below it cannot
     disagree about the stage or the set time. */
  const where = `${stage ? ` for ${stage}` : ''}${artist?.set_start ? `, ${setTime(artist.set_start)}` : ''}`

  const reading = isHelp
    ? [
        ticket.summary,
        firstMove ? firstMove.detail : 'Bumpin has not worked out a replacement slot yet.',
        `${actions.length} ${actions.length === 1 ? 'consequence' : 'consequences'}, each approved on its own.`,
      ]
    /* Dj Nova sent two documents with one conflict on each, so the reading is
       written per document: the generic one below describes both at once and
       therefore describes neither of the pages you are looking at. */
    : isDjNova(ticket)
    ? djNovaReading(doc?.filename, where)
    : [
        /* What they want. */
        req
          ? [
              `${ticket.owner.name ?? 'This act'} asks for `,
              req.technical > 0 && req.hospitality > 0
                ? `${req.technical} technical and ${req.hospitality} hospitality requirements`
                : `${req.total} ${req.total === 1 ? 'requirement' : 'requirements'}`,
              stage ? ` for ${stage}` : '',
              artist?.set_start ? `, ${setTime(artist.set_start)}` : '',
              '.',
            ].join('')
          : ticket.summary,
        /* What is wrong with it — the boxes on the page, in words. */
        conflictLines.length === 0
          ? 'Nothing on this rider is in dispute.'
          : conflictLines.map((f) => f.message).join(' '),
        /* Whether we can cover it. */
        coverage,
      ]

  /* Only rows the backend can actually fill. "Agency", "Load-in", "Earliest
     now", "Channel", "Parse confidence" and "Linked" have no field behind them
     on /tickets, /artists or /documents, so they are left out.

     Each row is pushed on the formatted STRING being non-empty rather than on
     the raw field being present, because the date helpers answer '' for a
     timestamp they cannot parse. Testing the source would let that '' through
     and put a labelled blank row in the table. */
  const rows: DetailRow[] = []
  if (artist?.manager_name) rows.push({ label: 'Manager', value: artist.manager_name })
  /* Who to reply to. Resolving a shortage drafts a mail to this address, so the
     operator can read it before committing rather than after. */
  if (artist?.manager_email) rows.push({ label: 'Contact', value: artist.manager_email })
  if (stage) rows.push({ label: 'Stage', value: stage })
  /* The window, not just the downbeat: how long the stage is occupied is what
     decides whether a shortage can be covered by moving kit between sets. The
     end is bare hh:mm because it falls on the day the start already names. */
  const setFrom = setTime(artist?.set_start)
  const setTo = hhmm(artist?.set_end)
  if (setFrom) rows.push({ label: 'Set time', value: setTo ? `${setFrom} – ${setTo}` : setFrom })
  if (isHelp && firstMove?.new_start) {
    rows.push({ label: 'Proposed', value: `${setTime(firstMove.new_start)} – ${setTime(firstMove.new_end)}` })
  }
  /* The donut totals the rider but does not say what the total is made of, and
     the two halves are handled by different people — technical by the stage
     crew, hospitality by the green room. Zero is left out: a rider with no
     hospitality asks nothing of them, which is not a figure worth a row. */
  if (req && req.technical > 0) rows.push({ label: 'Technical', value: String(req.technical) })
  if (req && req.hospitality > 0) rows.push({ label: 'Hospitality', value: String(req.hospitality) })
  /* When the rider landed. Read against the set time above it, this is the
     warning the operator is actually after: how much runway is left to source
     the shortfall. */
  const arrived = setTime(ticket.created_at)
  if (arrived) rows.push({ label: 'Received', value: arrived })
  if (doc) rows.push({ label: 'Document', value: doc.filename })
  /* Only worth a row once there is more than one, and then it is the count that
     matters: the pane shows one file at a time, so this is what says the thumb
     strip below it leads somewhere. */
  if (ticket.documents.length > 1) {
    rows.push({ label: 'Documents', value: `${ticket.documents.length} files` })
  }

  /* The header rides on every document, not only the pasted-email ones. It
     used to be built for `kind === 'text'` alone, so an image or a PDF — which
     is most of them — opened with no caption at all and nothing on screen said
     whose rider you were reading. The second line is the file type and nothing
     else: the stage and set time are already in the rail, and repeating them
     here just made a long line nobody reads. */
  const header = doc
    ? {
        line1: `${ticket.owner.name ?? 'Unknown act'} · ${kindLabel(doc.kind).toUpperCase()}`,
        line1Overline: true,
        line2: fileType(doc.filename),
      }
    : undefined

  const card = isHelp
    ? actions.length > 0 && (
        <ChangeActionsCard
          summary={firstMove?.detail ?? ticket.summary}
          severity={ticket.severity}
          actions={actions}
          error={rowError}
          busy={busy}
          onApprove={approveAction}
          onDeny={denyAction}
          onApproveAll={approveAll}
          onViewDraft={() => { if (ticket.draft_email) setModalOpen(true) }}
        />
      )
    /* A function, so the warning card's "I understand" can close itself
       without writing anything to the finding. */
    : selectedFinding && ((dismiss: () => void) => (
        <FindingCard
          finding={selectedFinding}
          active={modalOpen}
          busy={findingBusy || resolving}
          resolving={resolving}
          error={resolveError}
          onResolve={() => void startResolve(selectedFinding.id)}
          onIgnore={() => void ignoreFinding(selectedFinding.id)}
          onAcknowledge={dismiss}
        />
      ))

  return (
    <Shell title={ticket.owner.name ?? ticket.summary}>
      {resolveNote && <p className={`${s.note} t-body-md`} role="status">{resolveNote}</p>}
      <div className={s.split}>
        <div className={s.left}>
          <DocumentPane
            docId={doc?.id ?? null}
            documents={ticket.documents}
            onDocument={setPickedDoc}
            kind={kind}
            highlights={highlights}
            header={header}
            page={page}
            onPage={setPage}
            onSelect={setSelected}
            text={text}
            anchored={card || undefined}
          />
        </div>

        <aside className={s.rail}>
          <ReadingPanel title="Bumpin’s reading" paragraphs={reading} />
          {ticket.type === 'rider_needs' && (
            <DecisionPanel ticket={ticket} onDecided={setTicket}
                           onViewDraft={() => { if (ticket.draft_email) setModalOpen(true) }} />
          )}
          {isHelp ? (
            <DonutPanel title="Steps" unit={actions.length === 1 ? 'step' : 'steps'}
                        slices={[
                          { label: 'Proposed', value: proposed, tone: 'pink' },
                          { label: 'Approved', value: approved, tone: 'green' },
                        ]} />
          ) : (
            /* Figma reads "Requests / 14 items / Conflicts / Parsed clean".
               `rider_items` now reaches the client as `requirements`, so this
               is that chart: the middle number is what the artist ASKED FOR,
               and the split is how much of it is in dispute. Counting
               findings instead answered a different question — "what went
               wrong" — and read 3 on a rider asking for fifteen things. */
            <DonutPanel title="Requirements"
                        unit={requirementCount === 1 ? 'requirement' : 'requirements'}
                        slices={[
                          { label: 'Conflicts', value: conflictCount, tone: 'pink' },
                          { label: 'Clean', value: Math.max(0, requirementCount - conflictCount), tone: 'green' },
                        ]} />
          )}
          <DetailsPanel rows={rows} />
        </aside>
      </div>

      {/* Nothing opens the panel without a draft behind it any more: Resolve
          creates the draft first and only then opens on it. */}
      {modalOpen && ticket.draft_email && (
        <ResolveModal draft={ticket.draft_email} busy={findingBusy} error={sendError}
                      onSend={sendDraft} onClose={() => setModalOpen(false)} />
      )}
    </Shell>
  )
}

/** 118:29 Back + 118:32 Ticket title — the same on both layouts. */
function Shell({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <>
      <Link to="/riders" className={`${s.back} t-label-md`}>
        <svg className={s.backIcon} width="5" height="10" viewBox="0 0 5 10" fill="none"
             stroke="currentColor" strokeWidth="1.6" aria-hidden>
          <path d="M 5 0 L 0 5 L 5 10" />
        </svg>
        Open tickets
      </Link>
      <h1 className={`${s.title} t-display-lg`}>{title ?? 'Ticket'}</h1>
      {children}
    </>
  )
}
