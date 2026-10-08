import { useMemo, useState } from 'react'
import { Card, Row, StatusPill } from '@/components/primitives'
import { matches, useSearch } from '@/components/search'
import type { TicketStatus, TicketSummary, TicketType } from '@/api/types'
import s from './overview.module.css'

/* "Card — Open tickets" 17:2, empty specimen 231:413. */

/** `owner` and `open_findings` now live on `TicketSummary` itself — the shared
 *  type was widened against the live response, so no local widening is needed. */
export type TicketRow = TicketSummary

/** Progress is "conflicts resolved / conflicts raised". `/tickets` rows carry
 *  only `open_findings`, which counts every severity, so the tally has to come
 *  from each ticket's detail — Overview fetches it and passes it down. */
export type ConflictTally = { raised: number; resolved: number }

type Tab = { key: string; label: string; type: TicketType | null }

/* 17:5 / 17:7 / 17:9 / 17:11 */
const TABS: Tab[] = [
  { key: 'all', label: 'All', type: null },
  { key: 'riders', label: 'Riders', type: 'rider_needs' },
  { key: 'vendors', label: 'Vendors', type: 'vendor_eligibility' },
  /* No Help tab. Help tickets still list under All; they were a third of the
     tab row for a type the operator does not filter by on this screen. */
]

/* The design's six pills are Needs review / Verified / In progress / Expiring
   / Resolved / Overdue. Three of those are exact matches for a `TicketStatus`;
   Verified, Expiring and Overdue have no backend equivalent, and `open`,
   `approved` and `rejected` have no pill in the design. Tones are the Figma
   fills: yellow = warn, green = ok, pink = progress, sunken = neutral. */
const STATUS: Record<TicketStatus, { label: string; tone: 'ok' | 'progress' | 'warn' | 'neutral' }> = {
  open: { label: 'Open', tone: 'neutral' },
  needs_review: { label: 'Needs review', tone: 'warn' },
  in_progress: { label: 'In progress', tone: 'progress' },
  approved: { label: 'Approved', tone: 'ok' },
  rejected: { label: 'Rejected', tone: 'neutral' },
  resolved: { label: 'Resolved', tone: 'ok' },
}

const SKIP = new Set(['the', 'and', '&', 'of'])

/** "Nova Sahar" -> NS, "The Ember Tide" -> ET, "Basil & Bone" -> BB. */
function initials(name: string) {
  const words = name.split(/\s+/).filter((w) => w && !SKIP.has(w.toLowerCase()))
  if (words.length === 0) return '?'
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[1][0]).toUpperCase()
}

const sourceName = (t: TicketRow) => t.owner?.name ?? `Ticket ${t.id}`

const DATE = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

/** "2026-10-07T23:07:51" -> "7 Oct 2026", as in 17:30. */
function received(iso: string) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : DATE.format(d)
}

/* The design's Type column is dropped: the All / Riders / Vendors / Help tabs
   directly above the table already discriminate on `tickets.type`, so the
   column repeated the active tab on every row. The % column is folded into
   Progress, which leaves the four columns below. */
const COLUMNS = ['Source', 'Status', 'Received', 'Progress']

/** 17:31 is a 180x6 r3 surface-sunken track and 17:32 the fill over it. Figma
 *  colours an unfinished bar yellow (17:32 at 70%, 17:102 at 15%) and a full
 *  one green (17:46, 17:88). */
function Progress({ tally }: { tally: ConflictTally | null | undefined }) {
  /* Findings only come back on the detail call, so a row whose detail fetch
     failed has no denominator at all — that is unknown, not nought. */
  if (!tally) return <span className={`${s.progressNote} t-body-sm`}>Unknown</span>

  /* Nothing was raised, so there is nothing to be a fraction of. A solid track
     would read as 0% and a full one as done; neither is true. */
  if (tally.raised === 0) return <span className={`${s.progressNote} t-body-sm`}>No conflicts</span>

  const pct = Math.round((tally.resolved / tally.raised) * 100)
  return (
    <span
      className={s.progress}
      role="img"
      aria-label={`${tally.resolved} of ${tally.raised} conflicts resolved`}
    >
      <span className={s.bar}>
        <span
          className={`${s.barFill} ${pct === 100 ? s.barFillDone : ''}`}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className={`${s.pct} t-label-sm`}>{pct}%</span>
    </span>
  )
}

export function TicketsCard({ tickets, conflicts, error }: {
  tickets: TicketRow[] | null
  /** Keyed by ticket id. A missing or null entry means the detail fetch for
   *  that row failed; the row degrades to "Unknown" on its own. */
  conflicts: ReadonlyMap<number, ConflictTally | null>
  error: string | null
}) {
  const [tab, setTab] = useState('all')
  const { q } = useSearch()
  const query = q.trim()

  /* The tab and the query compose: a row has to clear both. */
  const rows = useMemo(() => {
    if (!tickets) return null
    const want = TABS.find((t) => t.key === tab)?.type ?? null
    return tickets.filter((t) =>
      (want === null || t.type === want) &&
      matches(q, sourceName(t), t.summary, STATUS[t.status].label))
  }, [tickets, tab, q])

  return (
    <Card className={s.ticketsCard}>
      <header className={s.head}>
        <div className={s.headText}>
          <h2 className={`${s.tableTitle} t-heading-sm`}>Open tickets</h2>
          <p className={`${s.tableSub} t-caption`}>
            Parsed from email by Bumpin
          </p>
        </div>
        <div className={s.tabs} role="tablist" aria-label="Filter tickets by type">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              className={`${s.tab} ${tab === t.key ? s.tabOn : ''} t-label-sm`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </header>

      <div className={s.table} role="table" aria-label="Open tickets">
        <div className={s.thead} role="row">
          {COLUMNS.map((c) => (
            <span key={c} className="t-overline" role="columnheader">{c}</span>
          ))}
        </div>

        {error !== null ? (
          <p className={`${s.tableNote} t-body-md`}>Could not load tickets: {error}</p>
        ) : rows === null ? (
          <p className={`${s.tableNote} t-body-md`}>Loading tickets…</p>
        ) : rows.length === 0 && query !== '' ? (
          /* Not the empty state: there are tickets, the query just excluded
             them all, and saying "No tickets yet" would misreport that. */
          <p className={`${s.tableNote} t-body-md`}>No tickets match “{query}”.</p>
        ) : rows.length === 0 ? (
          /* 231:763 */
          <div className={s.tableEmpty}>
            <p className={`${s.tableEmptyTitle} t-heading-sm`}>No tickets yet</p>
            <p className={`${s.tableEmptyBody} t-body-md`}>
              Tickets appear here as emails arrive and documents are parsed.
            </p>
          </div>
        ) : (
          <div className={s.tbody}>
            {rows.map((t) => {
              const name = sourceName(t)
              const status = STATUS[t.status]
              return (
                <Row key={t.id}>
                  <div className={s.source}>
                    <span className={`${s.avatar} t-label-sm`} aria-hidden>{initials(name)}</span>
                    <div className={s.sourceText}>
                      <div className={`${s.sourceName} t-label-md`}>{name}</div>
                      {/* The design's second line is the sender's email. No
                          field on /tickets carries it — see the report. */}
                    </div>
                  </div>
                  <span className={s.statusCell}>
                    <StatusPill label={status.label} tone={status.tone} />
                  </span>
                  <span className={`${s.date} t-body-sm`}>{received(t.created_at)}</span>
                  <Progress tally={conflicts.get(t.id)} />
                </Row>
              )
            })}
          </div>
        )}
      </div>
    </Card>
  )
}
