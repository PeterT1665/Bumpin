import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { TopBar } from '@/components/AppShell'
import { Stat, StatStrip } from '@/components/primitives'
import { matches, useSearch } from '@/components/search'
import { api } from '@/api/client'
import type { Artist } from '@/api/types'
import {
  conflictsOf, initials, shortDate, tintFor,
  type ConflictTally, type RiderTicket,
} from './riders'
import s from './RiderNeeds.module.css'

/* Figma 86:2 "Bumpin — Rider needs", with 111:2 for the new-column state and
   231:766 for the empty board. */

const POLL_MS = 3000

/** 101:7 — a 9x4.5 chevron in a 10x6 box, stroke #7a7161, 1.5, round caps. */
const Chevron = () => (
  <svg className={s.chevron} width="10" height="6" viewBox="-0.5 -0.8 10 6" fill="none"
       stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden>
    <path d="M 0 0 L 4.5 4.5 L 9 0" />
  </svg>
)

function Control({ label, value, onClick }: { label: string; value: string; onClick?: () => void }) {
  return (
    <button type="button" className={`${s.control} t-label-md`} onClick={onClick}>
      {label}: {value}
      <Chevron />
    </button>
  )
}

/** 231:1164 — the dash pattern is 10/8, which only an SVG stroke can carry.
 *  An empty column means one of two different things, so the caption says
 *  which: nothing has been filed against the stage at all, or everything filed
 *  there is hidden by the current search. */
function Placeholder({ caption }: { caption: string }) {
  return (
    <div className={s.placeholder}>
      {/* The column is a fixed 240x96 (231:1164), so the viewBox is 1:1 and the
          dash pattern and radius land exactly as drawn. */}
      <svg className={s.placeholderEdge} width="240" height="96" viewBox="0 0 240 96" aria-hidden>
        <rect x="0.5" y="0.5" width="239" height="95" rx="23.5"
              fill="none" stroke="currentColor" strokeWidth="1" strokeDasharray="10 8" />
      </svg>
      <p className={`${s.placeholderCaption} t-caption`}>{caption}</p>
    </div>
  )
}

/** The card's own heading: the ticket summary with the owner name stripped off
 *  the front, because the owner already shows in the footer. The search reads
 *  the same string the card draws, so a hit always has something visible. */
function cardTitle(ticket: RiderTicket): string {
  const name = ticket.owner?.name ?? ''
  return name && ticket.summary.startsWith(`${name}: `)
    ? ticket.summary.slice(name.length + 2)
    : ticket.summary
}

/** 88:8 — one ticket per card.
 *
 *  The bar is the ticket's conflicts: one segment per conflict raised, filled
 *  black once that conflict has been dealt with. A ticket with no conflicts has
 *  no denominator, so it gets no track at all rather than an empty one — an
 *  empty track reads as "none done", which is a different thing. */
function TicketCard({ ticket, stageless, conflicts }: {
  ticket: RiderTicket
  stageless: boolean
  /** `null` until the ticket's findings have loaded, or if that fetch failed. */
  conflicts: ConflictTally | null
}) {
  const name = ticket.owner?.name ?? ''
  const tint = tintFor(conflicts ?? { raised: 0, resolved: 0 })
  const title = cardTitle(ticket)

  return (
    <Link to={`/tickets/${ticket.id}`} className={`${s.card} ${s[`tint_${tint}`]}`}
          aria-label={`${name || 'Ticket'} · ${title}`}>
      <div className={s.titleRow}>
        <h3 className={`${s.cardTitle} t-heading-sm`}>{title}</h3>
        <span className={`${s.more} t-body-md-b`} aria-hidden>&#8226;&#8226;&#8226;</span>
      </div>
      {conflicts === null ? (
        <p className={`${s.noConflicts} t-caption`}>Counting conflicts…</p>
      ) : conflicts.raised === 0 ? null : (
        <div className={s.progress} role="img"
             aria-label={`${conflicts.resolved} of ${conflicts.raised} conflicts resolved`}>
          {Array.from({ length: conflicts.raised }, (_, i) => (
            <span key={i} className={`${s.seg} ${i < conflicts.resolved ? s.segOn : ''}`} />
          ))}
        </div>
      )}
      <div className={s.footer}>
        <span className={`${s.avatar} t-label-sm`} aria-hidden>{initials(name)}</span>
        <div className={s.meta}>
          <p className={`${s.metaName} t-body-md-b`}>{name || 'Unassigned'}</p>
          <p className={`${s.metaDate} t-body-sm`}>
            {stageless ? 'No stage yet' : shortDate(ticket.updated_at)}
          </p>
        </div>
      </div>
    </Link>
  )
}

type Column = { key: string; name: string; tickets: RiderTicket[] }

export function RiderNeeds() {
  const [tickets, setTickets] = useState<RiderTicket[] | null>(null)
  const [artists, setArtists] = useState<Artist[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  /** Conflicts raised and cleared per ticket, for the card bars. */
  const [conflicts, setConflicts] = useState<ReadonlyMap<number, ConflictTally | null>>(new Map())
  /** Columns the operator added locally. The backend has no stage-create
   *  endpoint, so an added column lives in this screen only. */
  const [extraColumns, setExtraColumns] = useState<string[]>([])
  const [draftColumn, setDraftColumn] = useState<string | null>(null)
  const draftRef = useRef<HTMLInputElement | null>(null)
  /* The top bar owns the query. Reading it rather than copying it into state
     keeps the reset-on-navigation in SearchProvider working. */
  const { q } = useSearch()
  const filtering = q.trim() !== ''

  const load = useCallback(async () => {
    try {
      const [t, a] = await Promise.all([
        api.tickets({ type: 'rider_needs' }) as Promise<RiderTicket[]>,
        api.artists(),
      ])
      setTickets(t)
      setArtists(a)
      setError(null)
      /* `GET /tickets` carries `open_findings` — a count of every open finding,
         any severity — which cannot answer "how many conflicts, how many
         cleared". Only the detail route carries the findings themselves, so the
         tallies are a second pass. It runs after the rows are set, so the board
         paints immediately and the bars fill when they arrive. A detail that
         fails leaves that one card unknown rather than failing the board. */
      const pairs = await Promise.all(t.map(async (row) => {
        try { return [row.id, conflictsOf((await api.ticket(row.id)).findings)] as const }
        catch { return [row.id, null] as const }
      }))
      setConflicts(new Map(pairs))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load rider needs')
    }
  }, [])

  useEffect(() => {
    let alive = true
    const tick = () => { if (alive) void load() }
    tick()
    const id = window.setInterval(tick, POLL_MS)
    return () => { alive = false; window.clearInterval(id) }
  }, [load])

  useEffect(() => { if (draftColumn !== null) draftRef.current?.focus() }, [draftColumn])

  /* Stage per ticket comes from /artists — the ticket row carries only the
     owner, so the board grouping is a join, not a ticket field. */
  const stageOf = useMemo(() => {
    const m = new Map<number, string | null>()
    for (const a of artists ?? []) m.set(a.id, a.stage_name)
    return m
  }, [artists])

  /** The cards the top-bar query leaves standing. Owner name and card title are
   *  both read, so either half of what a card draws finds it. */
  const shown = useMemo(
    () => (tickets ?? []).filter((t) => matches(q, t.owner?.name, cardTitle(t))),
    [tickets, q],
  )

  const columns = useMemo<Column[]>(() => {
    const stages: string[] = []
    for (const a of artists ?? []) {
      if (a.stage_name && !stages.includes(a.stage_name)) stages.push(a.stage_name)
    }
    stages.sort((x, y) => x.localeCompare(y))
    const all = [...stages, ...extraColumns.filter((c) => !stages.includes(c))]
    const byStage = new Map<string, RiderTicket[]>(all.map((n) => [n, []]))
    const stageFor = (t: RiderTicket) =>
      t.owner?.type === 'artist' ? stageOf.get(t.owner.id) ?? null : null
    const placed = (stage: string | null) => stage !== null && byStage.has(stage)

    const unstaged: RiderTicket[] = []
    for (const t of shown) {
      const stage = stageFor(t)
      if (placed(stage)) byStage.get(stage as string)!.push(t)
      else unstaged.push(t)
    }
    const out: Column[] = all.map((n) => ({ key: n, name: n, tickets: byStage.get(n) ?? [] }))
    /* "Not scheduled" exists whenever any ticket is unplaced, matched or not, so
       the board keeps its shape while a query is being typed. */
    if ((tickets ?? []).some((t) => !placed(stageFor(t)))) {
      out.push({ key: '__unstaged', name: 'Not scheduled', tickets: unstaged })
    }
    return out
  }, [artists, tickets, shown, extraColumns, stageOf])

  /* Counted off the same conflict tally the cards are tinted by, not off
     `ticket.status`. The two disagree: a ticket with two conflicts and one
     dealt with is still `needs_review` to the backend but is visibly
     half-done on the board, and a strip reading "In progress 0" above three
     part-finished cards is the screen contradicting itself. */
  const counts = useMemo(() => {
    let needsReview = 0, inProgress = 0, resolved = 0
    for (const t of tickets ?? []) {
      const c = conflicts.get(t.id)
      if (!c) continue                      // still loading, or its fetch failed
      if (c.raised === 0 || c.resolved >= c.raised) resolved++
      else if (c.resolved === 0) needsReview++
      else inProgress++
    }
    return { needsReview, inProgress, resolved }
  }, [tickets, conflicts])

  const commitColumn = () => {
    const name = (draftColumn ?? '').trim()
    if (name && !columns.some((c) => c.name === name)) setExtraColumns((x) => [...x, name])
    setDraftColumn(null)
  }

  return (
    <>
      <TopBar title="Rider needs" placeholder="Search artists and ticket titles" />

      {/* 87:14 */}
      <div className={s.controls}>
        <div className={s.dropdowns}>
          <Control label="Sort" value="Received" />
          <Control label="Group" value="Stage" />
          <Control label="Filter" value="All types" />
        </div>
        {/* 87:28 — rules read yellow / pink / green off 111:65, 111:69, 111:73. */}
        <StatStrip>
          <Stat label="Needs review" value={counts.needsReview} rule="yellow" />
          <Stat label="In progress" value={counts.inProgress} rule="pink" />
          <Stat label="Resolved" value={counts.resolved} rule="green" />
        </StatStrip>
      </div>

      {/* The three stats above are the whole board's tally, not the search's, so
          while a query is live the screen says so in as many words. */}
      {filtering && tickets !== null && (
        <p className={`${s.filterNote} t-body-sm`} role="status">
          Showing {shown.length} of {tickets.length}{' '}
          {tickets.length === 1 ? 'ticket' : 'tickets'} matching &ldquo;{q.trim()}&rdquo;.
          The counts above still cover every ticket.
        </p>
      )}

      {error && <p className={`${s.error} t-body-md`}>{error}</p>}
      {!error && tickets === null && <p className={`${s.loading} t-body-md`}>Loading rider needs…</p>}

      {tickets !== null && (
        <div className={s.board}>
          {columns.map((col) => (
            <section key={col.key} className={s.column}>
              <div className={s.rule} aria-hidden />
              <div className={s.colHead}>
                <h2 className={`${s.colName} t-label-md`}>{col.name}</h2>
                <button type="button" className={s.plus} aria-label={`Add to ${col.name}`} />
              </div>
              {col.tickets.length === 0
                ? <Placeholder caption={filtering ? 'No matches here' : 'Nothing filed'} />
                : col.tickets.map((t) => (
                    <TicketCard key={t.id} ticket={t} stageless={col.key === '__unstaged'}
                                conflicts={conflicts.get(t.id) ?? null} />
                  ))}
            </section>
          ))}

          {/* 115:26 collapsed, 116:2 while being named. */}
          <section className={s.column}>
            <div className={s.rule} aria-hidden />
            <div className={`${s.colHead} ${draftColumn === null ? s.colHeadAdd : ''}`}>
              {draftColumn === null ? (
                <button type="button" className={s.plus} aria-label="Add a column"
                        onClick={() => setDraftColumn('')} />
              ) : (
                <span className={s.nameEditing}>
                  <input ref={draftRef} className={s.nameInput} value={draftColumn}
                         placeholder="New Stage" aria-label="New column name"
                         onChange={(e) => setDraftColumn(e.target.value)}
                         onBlur={commitColumn}
                         onKeyDown={(e) => {
                           if (e.key === 'Enter') commitColumn()
                           if (e.key === 'Escape') setDraftColumn(null)
                         }} />
                  <span className={s.caret} aria-hidden />
                </span>
              )}
            </div>
          </section>
        </div>
      )}
    </>
  )
}
