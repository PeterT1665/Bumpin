import type { Allocation, InventoryItem, RunsheetRow } from '@/api/types'

/* Everything the two schedule tables need that the backend does not send.
   Pure functions, no React, so the arithmetic can be checked on its own. */

const TS = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/

/** "2026-12-12T18:00:00" -> "18:00". */
export function clock(ts: string): string {
  const m = TS.exec(ts)
  return m ? `${m[4]}:${m[5]}` : ts
}

/** Figma 216:9 — "17:00 – 18:00". En dash U+2013, one space either side. */
export const timeRange = (start: string, end: string) =>
  `${clock(start)} – ${clock(end)}`

const WEEKDAYS = [
  'Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday',
]
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

/** Figma 214:3 — the card title is the selected day spelled out in full,
 *  "Saturday 12 December". Parsed by hand so the naive timestamps the backend
 *  sends are never shifted by the browser's timezone. */
export function longDay(ts: string): string {
  const m = TS.exec(ts)
  if (!m) return ''
  const y = Number(m[1]), mo = Number(m[2]), d = Number(m[3])
  const weekday = WEEKDAYS[new Date(Date.UTC(y, mo - 1, d)).getUTCDay()]
  return `${weekday} ${d} ${MONTHS[mo - 1]}`
}

/* ---------------------------------------------------------------- status -- */

export type PillTone = 'ok' | 'progress' | 'warn' | 'neutral'

/** The rows carry the backend's vocabulary (`applied` / `in_progress` /
 *  `completed`); the design's pills read "Confirmed" and "In progress"
 *  (Figma 216:13 green #9eab6c, 216:40 pink #eba2d5). Mapped here, and only
 *  here, so the mismatch stays visible. */
export function statusPill(status: string): { label: string; tone: PillTone } {
  switch (status) {
    case 'completed':   return { label: 'Confirmed',   tone: 'ok' }
    case 'in_progress': return { label: 'In progress', tone: 'progress' }
    case 'applied':     return { label: 'Applied',     tone: 'neutral' }
    default:            return { label: status, tone: 'neutral' }
  }
}

/** The row's kind as a reader would say it. Nothing draws this — the Run sheet
 *  tells sets from load-ins by their place in the day — but the search needs a
 *  word to match, and `load_in` is not one. */
export function kindLabel(kind: RunsheetRow['kind']): string {
  return kind === 'set' ? 'Set' : 'Load-in'
}

/* ----------------------------------------------------------------- needs -- */

/** Half-open overlap on the backend's naive ISO strings, which sort correctly
 *  as text because they are all the same fixed-width format. */
const overlaps = (aStart: string, aEnd: string, bStart: string, bEnd: string) =>
  aStart < bEnd && bStart < aEnd

/** The design's Needs column is the approved technical rider. `/runsheet` has
 *  no such field, so it is rebuilt from the reservations those riders wrote
 *  into `/inventory`: an allocation belongs to a row when it names the same
 *  artist and covers the same slot. Load-ins never carry a rider.
 *
 *  Figma 216:11 writes quantities as "4× SM58" and drops the count when it is
 *  one ("Moog One, keys stand, …"), which is the rule applied here. */
export function needsFor(row: RunsheetRow, inventory: InventoryItem[]): string {
  if (row.kind !== 'set') return ''
  const parts: string[] = []
  for (const item of inventory) {
    for (const a of item.allocations) {
      if (a.artist_name !== row.who) continue
      if (!overlaps(a.start_ts, a.end_ts, row.start, row.end)) continue
      parts.push(a.quantity > 1
        ? `${a.quantity}× ${item.canonical_name}`
        : item.canonical_name)
    }
  }
  return parts.join(', ')
}

/* ------------------------------------------------------------- inventory -- */

export type ItemFlag = 'Shortage' | 'Clash' | null

export interface ItemRow {
  key: string
  id: number
  name: string
  category: string
  where: string
  total: number
  reserved: number
  free: number
  heldBy: string[]
  flag: ItemFlag
}

/** More of an item committed at one moment than the venue owns.
 *
 *  Two artists holding the same item at the same time is NOT a clash on its
 *  own: a pool of two keyboard stands covers two simultaneous sets exactly,
 *  and calling that a clash flags a perfectly booked item. What matters is
 *  whether demand at any instant exceeds the pool, so this sweeps the
 *  allocation starts — the only moments at which concurrent demand can rise —
 *  and compares what is held then against what exists. */
function clashes(allocations: Allocation[], total: number): boolean {
  return allocations.some((at) =>
    allocations
      .filter((a) => a.start_ts <= at.start_ts && at.start_ts < a.end_ts)
      .reduce((n, a) => n + a.quantity, 0) > total,
  )
}

/** Reserved is the sum of the allocations on the item; Free is total minus
 *  reserved. Both are computed here rather than read, because the backend
 *  sends neither. */
export function itemRows(inventory: InventoryItem[]): ItemRow[] {
  return inventory.map((item) => {
    const reserved = item.allocations.reduce((n, a) => n + a.quantity, 0)
    const heldBy = [...new Set(
      item.allocations
        .map((a) => a.artist_name)
        .filter((n): n is string => typeof n === 'string' && n.length > 0),
    )]
    return {
      key: String(item.id),
      /** The row's own id, so it can be removed. `key` is a string for React
       *  and must stay one; this is the number the endpoint wants. */
      id: item.id,
      name: item.canonical_name,
      category: item.category,
      // Figma 228:125 — an item with no stage reads "Shared pool".
      where: item.stage_name ?? 'Shared pool',
      total: item.quantity_total,
      reserved,
      free: item.quantity_total - reserved,
      heldBy,
      flag: reserved > item.quantity_total
        ? 'Shortage'
        : clashes(item.allocations, item.quantity_total) ? 'Clash' : null,
    }
  })
}
