import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '@/api/client'
import type { RecentEmail } from '@/api/types'
import styles from './Arrivals.module.css'

/* New email while the laptop app is open: a toast for the latest one and a count
   on the rail for each section with unseen arrivals. It watches emails, not
   tickets, so a revised rider that updates an existing ticket is announced too.
   The first load only learns what already exists, so nothing old is announced. */

const POLL_MS = 3000
const TOAST_MS = 10000

export type Section = '/riders' | '/vendors'

const sectionOf = (e: RecentEmail): Section =>
  e.ticket_type === 'vendor_eligibility' || e.owner_type === 'vendor' ? '/vendors' : '/riders'

export const hrefOf = (e: RecentEmail) =>
  sectionOf(e) === '/vendors' && e.owner_id ? `/vendors/${e.owner_id}` : `/tickets/${e.ticket_id}`

export function labelOf(e: RecentEmail) {
  if (e.ticket_type === 'help') return 'Change request'
  if (e.ticket_type === 'vendor_eligibility') return 'Vendor email'
  return e.updated_existing ? 'Revised rider' : 'New rider'
}

export function useArrivals() {
  const [unseen, setUnseen] = useState<RecentEmail[]>([])
  const [toast, setToast] = useState<RecentEmail | null>(null)
  const lastId = useRef<number | null>(null)
  const { pathname } = useLocation()

  const poll = useCallback(async () => {
    try {
      const rows = await api.recentEmails()
      const newest = rows.reduce((m, r) => Math.max(m, r.email_id), 0)
      // A demo reset drops the ids back down: start counting from there.
      if (lastId.current !== null && newest >= lastId.current) {
        const added = rows.filter((r) => r.email_id > lastId.current!).reverse()
        if (added.length) {
          setUnseen((prev) => [...prev, ...added])
          setToast(added[added.length - 1])
        }
      }
      lastId.current = newest
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
    setUnseen((prev) => prev.filter((e) => !pathname.startsWith(sectionOf(e)) && pathname !== hrefOf(e)))
  }, [pathname])

  const badges: Partial<Record<Section, number>> = {}
  for (const e of unseen) badges[sectionOf(e)] = (badges[sectionOf(e)] ?? 0) + 1

  return { badges, toast, dismiss: () => setToast(null) }
}

export function ArrivalToast({ email, onClose }: { email: RecentEmail; onClose: () => void }) {
  return (
    <div className={styles.toast} role="status" aria-live="polite">
      <span className={`${styles.tag} t-overline`}>{labelOf(email)}</span>
      <div className={styles.text}>
        <p className={`${styles.who} t-label-md`}>{email.owner_name ?? email.from_addr}</p>
        <p className={`${styles.what} t-body-sm`}>{email.summary || email.subject}</p>
      </div>
      <Link className={`${styles.open} t-label-md`} to={hrefOf(email)} onClick={onClose}>Open</Link>
      <button type="button" className={styles.close} aria-label="Dismiss" onClick={onClose}>&#215;</button>
    </div>
  )
}
