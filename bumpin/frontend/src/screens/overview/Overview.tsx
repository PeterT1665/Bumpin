import { useEffect, useState } from 'react'
import { TopBar } from '@/components/AppShell'
import { ACTOR, api } from '@/api/client'
import type { Overview as OverviewData } from '@/api/types'
import { IntakeCard, ReadinessCard, SpendCard } from './StatCards'
import { TicketsCard, type ConflictTally, type TicketRow } from './TicketsCard'
import s from './overview.module.css'

/* "Bumpin — Dashboard" 13:2, empty case "Screen — Overview · empty" 231:385.
   The nav rail and the top bar are AppShell's; this is the canvas. */

const name = ACTOR.charAt(0).toUpperCase() + ACTOR.slice(1)

/** The tickets table's Progress column is conflicts resolved over conflicts
 *  raised, and only `GET /tickets/{id}` carries findings — the list's
 *  `open_findings` counts every severity, so it cannot supply either number.
 *  Nine rows makes nine parallel detail calls cheap. Each is caught on its own
 *  so one failure costs that row its figure rather than the whole card. */
async function conflictTallies(tickets: TicketRow[]) {
  const entries = await Promise.all(tickets.map(async (t): Promise<[number, ConflictTally | null]> => {
    try {
      const detail = await api.ticket(t.id)
      const raised = detail.findings.filter((f) => f.severity === 'conflict')
      // 'ignored' is a decision too, so anything no longer open counts as dealt with.
      return [t.id, { raised: raised.length, resolved: raised.filter((f) => f.status !== 'open').length }]
    } catch {
      return [t.id, null]
    }
  }))
  return new Map(entries)
}

export function Overview() {
  const [overview, setOverview] = useState<OverviewData | null>(null)
  const [tickets, setTickets] = useState<TicketRow[] | null>(null)
  const [conflicts, setConflicts] = useState<ReadonlyMap<number, ConflictTally | null>>(new Map())
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    Promise.all([api.overview(), api.tickets()])
      .then(async ([o, t]) => {
        if (!alive) return
        setOverview(o)
        setTickets(t)
        // Rows render first and fill their Progress cell when the details land.
        const tallies = await conflictTallies(t)
        if (alive) setConflicts(tallies)
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e))
      })
    return () => { alive = false }
  }, [])

  return (
    <>
      {/* 14:54 — the greeting is the top bar's title on this screen. */}
      <TopBar
        title={`Welcome back, ${name}`}
        placeholder="Search tickets by source, summary or status"
      />

      <div className={s.cardRow}>
        <IntakeCard intake={overview?.intake} />
        <SpendCard hospitality={overview?.hospitality} />
        <ReadinessCard
          readinessPct={overview?.readiness_pct ?? null}
          readiness={overview?.readiness}
        />
      </div>

      <div className={s.ticketsRow}>
        <TicketsCard tickets={tickets} conflicts={conflicts} error={error} />
      </div>
    </>
  )
}
