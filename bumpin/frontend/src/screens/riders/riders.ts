/* Helpers shared by the two Riders screens.
   Every literal in here was read off a Figma node; the node id is named at the
   value. Nothing is guessed. */

import type { Finding, Severity, TicketStatus, TicketSummary } from '@/api/types'

/** `GET /tickets` really returns `owner` and `open_findings` on each row, but
 *  `TicketSummary` in api/types.ts (which this slice does not own) stops at the
 *  bare ticket. Widen locally rather than reach into a shared file. */
export type RiderTicket = TicketSummary & {
  owner?: { type: string; id: number; name: string | null } | null
  open_findings?: number
  decided_by?: string | null
}

/* ---- board card tint + conflict tally ------------------------------------ */

/** What a ticket's bar reports: how many conflicts it raised, and how many of
 *  those have been dealt with. A ticket can span several documents, so this
 *  counts findings rather than documents.
 *
 *  `ignored` counts as dealt with. It is a decision someone made about the
 *  conflict, the same as `resolved` — the open/closed split is what the bar is
 *  about, not which way it was closed. */
export type ConflictTally = { raised: number; resolved: number }

export function conflictsOf(findings: Pick<Finding, 'severity' | 'status'>[]): ConflictTally {
  const raised = findings.filter((f) => f.severity === 'conflict')
  return { raised: raised.length, resolved: raised.filter((f) => f.status !== 'open').length }
}

/** Transcribed from all nineteen cards on Figma 88:2: #f0d977 (88:40),
 *  #eba2d5 (88:8, 88:56, 88:88, 88:141), #9eab6c (88:24, 88:72, 88:125).
 *
 *  The palette is the design's; what maps onto it is the tally. Nothing raised,
 *  or everything cleared, reads green. Nothing cleared yet reads yellow. Part
 *  way reads pink. */
export function tintFor(t: ConflictTally): 'yellow' | 'pink' | 'green' {
  if (t.raised === 0 || t.resolved >= t.raised) return 'green'
  if (t.resolved === 0) return 'yellow'
  return 'pink'
}

/* ---- text ---------------------------------------------------------------- */

const SKIP = new Set(['the', 'a', 'an', 'and', '&', 'of'])

/** "The Ember Tide" -> ET (88:20), "Kito Marenga" -> KM (88:36),
 *  "Sunbaker" -> SB (88:121). */
export function initials(name: string | null | undefined): string {
  if (!name) return '??'
  const words = name.split(/[\s—–-]+/).filter((w) => w && !SKIP.has(w.toLowerCase()))
  if (words.length === 0) return name.slice(0, 2).toUpperCase()
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[1][0]).toUpperCase()
}

/** "6.10.26" — Figma 88:23 / 88:39 / 88:55. D.M.YY, no zero padding. */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getDate()}.${d.getMonth() + 1}.${String(d.getFullYear()).slice(2)}`
}

/** "Sat 11 Oct, 21:15" — Figma 129:25. */
export function setTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const day = d.toLocaleDateString('en-AU', { weekday: 'short' })
  const date = d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
  return `${day} ${date}, ${hhmm(iso)}`
}

/** "22:45" */
export function hhmm(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** `double_booking` -> "Double booking". The Figma tags read "Low capacity",
 *  "Clash" and "Change"; those are specimen copy for findings the backend does
 *  not hold, so the tag carries the real `finding.kind` instead. */
export function kindLabel(kind: string): string {
  const s = kind.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/** Ticket status to the StatusPill tone the primitives expose. */
export function statusTone(s: TicketStatus): 'ok' | 'progress' | 'warn' | 'neutral' {
  if (s === 'resolved' || s === 'approved') return 'ok'
  if (s === 'in_progress') return 'progress'
  if (s === 'needs_review') return 'warn'
  return 'neutral'
}

/* ---- highlights ---------------------------------------------------------- */

/** Figma 119:29/119:30 (pink), 190:2/190:3 (yellow), 119:25/119:26 (blue).
 *  There is no red: conflict is a soft pink fill with dark text and a solid
 *  pink underline.
 *
 *  `info` keeps its blue even though the seed no longer stores any `info`
 *  finding. The DATA changed; `Severity` — which this slice does not own — did
 *  not, and the map is indexed with `HIGHLIGHT_TONE[h.severity]` at four call
 *  sites. Dropping the key makes those lookups `undefined`, which resolves to
 *  `mark_undefined` / `box_undefined`: a highlight with no fill and no
 *  underline, invisible on the page, the first time the backend emits an `info`
 *  finding again. A total map cannot fail that way, so blue stays here (and its
 *  `.mark_blue` / `.box_blue` / `.tag_blue` rules stay reachable through it). */
export const HIGHLIGHT_TONE: Record<Severity, 'pink' | 'yellow' | 'blue'> = {
  conflict: 'pink',
  warning: 'yellow',
  info: 'blue',
}

/* ---- donut --------------------------------------------------------------- */

/** Figma 129:8/129:9: two live segments start at -88deg and leave 4deg between
 *  them, so the usable sweep is 360 - 4*live. Figma 230:143: a single live
 *  segment is the full 360 with no gap. */
const GAP_DEG = 4

export function donutArcs(values: number[]): { from: number; to: number }[] {
  const total = values.reduce((a, b) => a + b, 0)
  if (total <= 0) return []
  const live = values.filter((v) => v > 0).length
  const usable = live > 1 ? 360 - GAP_DEG * live : 360
  let a = -90 + (live > 1 ? GAP_DEG / 2 : 0)
  const out: { from: number; to: number }[] = []
  for (const v of values) {
    if (v <= 0) continue
    const sweep = (v / total) * usable
    out.push({ from: a, to: a + sweep })
    a += sweep + GAP_DEG
  }
  return out
}
