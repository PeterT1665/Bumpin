import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '@/api/client'
import type { TicketSummary } from '@/api/types'
import styles from './Arrivals.module.css'

/* New tickets while the laptop app is open: a toast for the latest one and a
   count on the rail for each section that has unseen arrivals. Polls the same
   way the screens do; the first load only learns what already exists, so
   nothing pre-existing is announced. */

const POLL_MS = 3000
const TOAST_MS = 10000

export type Section = '/riders' | '/vendors'

const sectionOf = (t: TicketSummary): Section =>
  t.type === 'vendor_eligibility' || t.owner_type === 'vendor' ? '/vendors' : '/riders'

const hrefOf = (t: TicketSummary) =>
  sectionOf(t) === '/vendors' && t.owner_id ? `/vendors/${t.owner_id}` : `/tickets/${t.id}`

const LABEL: Record<TicketSummary['type'], string> = {
  rider_needs: 'New rider',
  vendor_eligibility: 'New vendor email',
  help: 'New change request',
}

export function useArrivals() {
  const [unseen, setUnseen] = useState<TicketSummary[]>([])
  const [toast, setToast] = useState<TicketSummary | null>(null)
  const known = useRef<Set<number> | null>(null)
  const { pathname } = useLocation()

  const poll = useCallback(async () => {
    try {
      const all = await api.tickets()
      if (known.current) {
        const added = all.filter((t) => !known.current!.has(t.id))
        if (added.length) {
          setUnseen((prev) => [...prev, ...added])
          setToast(added[added.length - 1])
        }
      }
      known.current = new Set(all.map((t) => t.id))
    } catch {
      // Backend briefly away: try again on the next tick.
    }
  }, [])

  useEffect(() => {
    void poll()
    const t = window.setInterval(() => void poll(), POLL_MS)
    return () => window.clearInterval(t)
  }, [poll])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), TOAST_MS)
    return () => window.clearTimeout(t)
  }, [toast])

  // Visiting a section, or the ticket itself, counts as having seen it.
  useEffect(() => {
    setUnseen((prev) => prev.filter((t) => !pathname.startsWith(sectionOf(t)) && pathname !== hrefOf(t)))
  }, [pathname])

  const badges: Partial<Record<Section, number>> = {}
  for (const t of unseen) badges[sectionOf(t)] = (badges[sectionOf(t)] ?? 0) + 1

  return { badges, toast, dismiss: () => setToast(null) }
}

export function ArrivalToast({ ticket, onClose }: { ticket: TicketSummary; onClose: () => void }) {
  return (
    <div className={styles.toast} role="status" aria-live="polite">
      <span className={`${styles.tag} t-overline`}>{LABEL[ticket.type]}</span>
      <div className={styles.text}>
        <p className={`${styles.who} t-label-md`}>{ticket.owner?.name ?? 'Unknown sender'}</p>
        <p className={`${styles.what} t-body-sm`}>{ticket.summary}</p>
      </div>
      <Link className={`${styles.open} t-label-md`} to={hrefOf(ticket)} onClick={onClose}>Open</Link>
      <button type="button" className={styles.close} aria-label="Dismiss" onClick={onClose}>&#215;</button>
    </div>
  )
}
