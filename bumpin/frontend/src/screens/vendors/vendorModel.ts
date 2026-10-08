/* Vendor slice domain helpers.
 *
 * Everything here is derived from fields the backend actually returns — see
 * docs/CONTRACT.md §7/§13 and backend/app/vendors/{routes,eligibility}.py.
 * Nothing in this file invents a category or a label that the API cannot fill.
 */

import type {
  DocumentRef, Finding, ProposedAction, Severity, TicketDetail, TicketStatus, Vendor,
} from '@/api/types'

/* ---------------------------------------------------------------- documents */

/** `GET /vendors/{id}` returns documents with one more field than `DocumentRef`. */
export interface VendorDocument extends DocumentRef {
  received_at: string | null
}

export interface VendorWithDocuments extends Vendor {
  documents: VendorDocument[]
}

/** The ticket list endpoint adds these two to every row. */
export interface VendorTicketRow {
  id: number
  type: string
  status: TicketStatus
  severity: Severity
  summary: string
  owner: { type: string; id: number | null; name: string | null } | null
  open_findings: number
  updated_at: string
}

/** Vendor load-in changes use a third action kind that `api/types.ts` has not
 *  got yet (`move_set` and `notify` are the artist kinds). Widened locally so
 *  this slice can read `kind === 'move_load_in'` without touching shared code. */
export type VendorActionKind = ProposedAction['kind'] | 'move_load_in'
export type VendorProposedAction = Omit<ProposedAction, 'kind'> & {
  kind: VendorActionKind
  vendor_id?: number | null
}

/** `shared/tickets.py` serialises `proposed_actions_json` with
 *  `json.loads(...) if ... else []`, so the wire value is always an array —
 *  `[]` for a document ticket, one entry for a load-in change. Both the
 *  documented `null` and the observed `[]` are treated as "document ticket". */
export const actionsOf = (t: TicketDetail | null): VendorProposedAction[] =>
  (t?.proposed_actions ?? []) as VendorProposedAction[]

export const isDocumentTicket = (t: TicketDetail | null) => actionsOf(t).length === 0

export const loadInAction = (t: TicketDetail | null) =>
  actionsOf(t).find((a) => a.kind === 'move_load_in') ?? null

/* ------------------------------------------------------- certificate groups */

/** The five groups the board shows, in the order of the Figma columns.
 *
 *  `kinds` maps onto the backend's `documents.kind` vocabulary
 *  (`rider, permit, food_safety, insurance, gas, other`). "Liquor licence" has
 *  no counterpart: neither the kind vocabulary nor
 *  `data/rules/vendor_eligibility.yaml` mentions liquor, so that column can
 *  only ever be empty. It is kept because the design asks for it. */
export interface CertGroup {
  id: string
  label: string
  /** Document kinds filed under this column. Empty = nothing can land here. */
  kinds: string[]
  /** Singular noun used in a card title. */
  noun: string
}

export const CERT_GROUPS: CertGroup[] = [
  { id: 'food_safety', label: 'Food safety', kinds: ['food_safety'], noun: 'Food safety cert' },
  { id: 'insurance', label: 'Public liability', kinds: ['insurance'], noun: 'Public liability' },
  { id: 'gas', label: 'Gas & electrical', kinds: ['gas'], noun: 'Gas compliance' },
  { id: 'permit', label: 'Council permit', kinds: ['permit'], noun: 'Council permit' },
  /* The design draws a fifth "Liquor licence" column, but no vendor type
     requires a liquor document and `kinds: []` means nothing can ever land in
     it — it was a permanently empty column pushing the board off screen. */
]

/** Kinds the four columns between them can hold. Anything outside this set
 *  (`other`, `rider`) would be dropped silently, so it is surfaced instead. */
export const GROUPED_KINDS = new Set(CERT_GROUPS.flatMap((g) => g.kinds))

export const groupForKind = (kind: string) =>
  CERT_GROUPS.find((g) => g.kinds.includes(kind)) ?? null

/** Document kinds each vendor type must file, transcribed from
 *  `data/rules/vendor_eligibility.yaml`. `gas` is added when `uses_gas`. */
const REQUIRED: Record<string, { required: string[]; gas: string[] }> = {
  food: { required: ['food_safety', 'insurance', 'permit'], gas: ['gas'] },
  beverage: { required: ['insurance', 'permit'], gas: ['gas'] },
  merch: { required: ['insurance'], gas: [] },
  other: { required: ['insurance', 'permit'], gas: ['gas'] },
}

export function requiredKinds(v: Pick<Vendor, 'type' | 'uses_gas'>): string[] {
  const rule = REQUIRED[v.type] ?? REQUIRED.other
  const out = [...rule.required]
  if (v.uses_gas) for (const k of rule.gas) if (!out.includes(k)) out.push(k)
  return out
}

export const KIND_LABEL: Record<string, string> = {
  food_safety: 'Food safety certificate',
  insurance: 'Public liability insurance',
  permit: 'Council trading permit',
  gas: 'Gas compliance certificate',
  rider: 'Rider',
  other: 'Other document',
}

export const kindLabel = (kind: string) => KIND_LABEL[kind] ?? kind

/* ------------------------------------------------------------------- tinting */

/** The three card tints on the board. "Valid on event day" is the whole
 *  question the board answers, so it is the only thing that picks a tint:
 *  blue when the expiry clears the festival end date, pink when it does not,
 *  yellow when there is nothing to compare (unread expiry, or no document). */
export type Tone = 'valid' | 'conflict' | 'awaiting'

export function toneForDocument(doc: VendorDocument | null, festivalEnd: string): Tone {
  if (!doc) return 'awaiting'
  if (!doc.expiry_date) return 'awaiting'
  return doc.expiry_date >= festivalEnd ? 'valid' : 'conflict'
}

/** The design's five-segment track, filled from five checks that read straight
 *  off the document row. Each is a field the backend either parsed or did not.
 *    1 received      — a document row exists
 *    2 kind read     — kind is one of the known vocabulary, not `other`
 *    3 issuer read   — `issuer` is set
 *    4 expiry read   — `expiry_date` is set
 *    5 valid on day  — `expiry_date` clears the festival end date
 *  Missing documents score 0. */
/** What a card's bar reports: conflicts raised on the vendor's ticket, and how
 *  many have been dealt with. It is a property of the TICKET, not of the one
 *  certificate the card stands for — a ticket can raise conflicts across
 *  several documents — so every card for the same vendor shows the same bar.
 *
 *  `ignored` counts as dealt with: it is a decision about the conflict, the
 *  same as `resolved`. The bar is about open versus closed, not which way. */
export type ConflictTally = { raised: number; resolved: number }

export function conflictsOf(findings: Pick<Finding, 'severity' | 'status'>[]): ConflictTally {
  const raised = findings.filter((f) => f.severity === 'conflict')
  return { raised: raised.length, resolved: raised.filter((f) => f.status !== 'open').length }
}

/** 0..1, for sorting. A vendor with no conflicts has nothing outstanding, so it
 *  ranks with the fully-cleared rather than with the untouched. */
export const clearedRatio = (t: ConflictTally | null | undefined) =>
  !t || t.raised === 0 ? 1 : t.resolved / t.raised

/* ----------------------------------------------------------------- sorting */

/** The board's sort options. Every one of them reads a field the card already
 *  carries: `tone` and `progress` are derived in `makeCard`, the expiry date and
 *  the vendor name come straight off the API rows. Nothing here needs a column
 *  the backend has not got (see HANDOFF §6) — a ticket-progress or
 *  last-changed sort would, which is why neither is offered. */
export type SortId = 'status' | 'name' | 'expiry' | 'progress'

export const SORTS: { id: SortId; label: string }[] = [
  { id: 'status', label: 'Status' },
  { id: 'name', label: 'Vendor A–Z' },
  { id: 'expiry', label: 'Soonest expiry' },
  { id: 'progress', label: 'Least resolved' },
]

/** Conflict first, then awaiting, then valid — the order the board was drawn in
 *  (159:472 pink, 159:488 yellow, 159:456 blue). */
export const TONE_RANK: Record<Tone, number> = { conflict: 0, awaiting: 1, valid: 2 }

/** Primary key per option. `expiry` has to cope with a missing date: a card with
 *  no readable expiry is the one thing a date sort can say nothing about, so
 *  nulls sort last instead of behaving like year zero and leading the column. */
const PRIMARY: Record<SortId, (a: BoardCard, b: BoardCard) => number> = {
  status: (a, b) => TONE_RANK[a.tone] - TONE_RANK[b.tone],
  name: () => 0,
  expiry: (a, b) => {
    const x = a.doc?.expiry_date ?? null
    const y = b.doc?.expiry_date ?? null
    if (x === y) return 0
    if (x === null) return 1
    if (y === null) return -1
    // ISO yyyy-mm-dd compares correctly as a string, so no Date parsing.
    return x < y ? -1 : 1
  },
  progress: (a, b) => clearedRatio(a.conflicts) - clearedRatio(b.conflicts),
}

/** Total, not merely stable: ties fall through to the vendor name and then to
 *  `card.key`, which is unique per card. The same data therefore renders in the
 *  same order however the cards arrived, so the order can be predicted from the
 *  API alone. */
export function sortCards(cards: BoardCard[], sort: SortId): BoardCard[] {
  const primary = PRIMARY[sort]
  return [...cards].sort(
    (a, b) => primary(a, b)
      || a.vendor.name.localeCompare(b.vendor.name)
      || a.key.localeCompare(b.key),
  )
}

/* ----------------------------------------------------------------- the board */

export interface BoardCard {
  key: string
  groupId: string
  vendor: Vendor
  doc: VendorDocument | null
  tone: Tone
  /** `null` while the ticket's findings are still loading, or if the vendor has
   *  no ticket at all — there is then no conflict count to draw. */
  conflicts: ConflictTally | null
  title: string
  date: string | null
}

/** One card per required certificate per vendor, plus a card for any document
 *  already on file that the rules do not require. A required kind with nothing
 *  on file still gets a card — that is the "awaiting broker copy" shape in the
 *  design, and the only way the board can show a hole. */
export function buildBoard(
  vendors: VendorWithDocuments[], festivalEnd: string,
  conflicts: ReadonlyMap<number, ConflictTally | null>,
) {
  const cards: BoardCard[] = []
  const unfiled: { vendor: Vendor; doc: VendorDocument }[] = []

  for (const v of vendors) {
    const seen = new Set<string>()
    for (const kind of requiredKinds(v)) {
      const group = groupForKind(kind)
      if (!group) continue
      seen.add(kind)
      const doc = newestOfKind(v.documents, kind)
      cards.push(makeCard(v, group.id, group.noun, doc, festivalEnd, conflicts))
    }
    for (const doc of v.documents) {
      if (seen.has(doc.kind)) continue
      const group = groupForKind(doc.kind)
      if (!group) { unfiled.push({ vendor: v, doc }); continue }
      cards.push(makeCard(v, group.id, group.noun, doc, festivalEnd, conflicts))
    }
  }

  const byGroup = new Map<string, BoardCard[]>(CERT_GROUPS.map((g) => [g.id, []]))
  for (const c of cards) byGroup.get(c.groupId)!.push(c)
  // 'status' is the board's designed order, so the model hands the screen a
  // column that already reads correctly before anyone touches the sort control.
  for (const [id, list] of byGroup) byGroup.set(id, sortCards(list, 'status'))

  const counts: Record<Tone, number> = { valid: 0, conflict: 0, awaiting: 0 }
  for (const c of cards) counts[c.tone]++

  return { byGroup, counts, unfiled, total: cards.length }
}

function makeCard(
  vendor: Vendor, groupId: string, noun: string,
  doc: VendorDocument | null, festivalEnd: string,
  conflicts: ReadonlyMap<number, ConflictTally | null>,
): BoardCard {
  const tone = toneForDocument(doc, festivalEnd)
  return {
    key: `${vendor.id}:${groupId}:${doc ? doc.id : 'none'}`,
    groupId,
    vendor,
    doc,
    tone,
    conflicts: vendor.latest_ticket_id ? conflicts.get(vendor.latest_ticket_id) ?? null : null,
    title: cardTitle(noun, doc, tone),
    date: doc?.received_at ? shortDate(doc.received_at) : null,
  }
}

/* The separator is a comma, not an em dash: the fourth branch already reads
   "Food safety cert, current to 2027", and a card title is a phrase rather than
   two halves of a headline. */
function cardTitle(noun: string, doc: VendorDocument | null, tone: Tone) {
  if (!doc) return `${noun}, not on file`
  if (!doc.expiry_date) return `${noun}, expiry unreadable`
  if (tone === 'conflict') return `${noun}, expires ${dayMonth(doc.expiry_date)}`
  return `${noun}, current to ${doc.expiry_date.slice(0, 4)}`
}

/** Newest document of a kind, matching `eligibility.latest_docs` which keeps
 *  the last row in id order. */
export function newestOfKind(docs: VendorDocument[], kind: string): VendorDocument | null {
  let found: VendorDocument | null = null
  for (const d of docs) if (d.kind === kind) found = d
  return found
}

/* -------------------------------------------------------------- formatting */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2.10.26" — the board card footer format. */
export function shortDate(iso: string) {
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${Number(d)}.${Number(m)}.${y.slice(2)}`
}

/** "19 Nov" */
export function dayMonth(iso: string) {
  const [, m, d] = iso.slice(0, 10).split('-')
  return `${Number(d)} ${MONTHS[Number(m) - 1]}`
}

/** "14 Nov 2026" — the details table format. */
export function longDate(iso: string | null) {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${Number(d)} ${MONTHS[Number(m) - 1]} ${y}`
}

/** "07:30" */
export const clockTime = (iso: string) => iso.slice(11, 16)

export function initials(name: string) {
  const words = name.replace(/[^A-Za-z0-9 ]/g, ' ').split(/\s+/).filter(Boolean)
  if (words.length === 0) return '??'
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[words.length - 1][0]).toUpperCase()
}

export const daysBetween = (a: string, b: string) =>
  Math.round((Date.parse(b.slice(0, 10)) - Date.parse(a.slice(0, 10))) / 86_400_000)

/* ----------------------------------------------------------------- findings */

export const openFindings = (t: TicketDetail | null) =>
  (t?.findings ?? []).filter((f) => f.status === 'open')

const SEVERITY_RANK: Record<Severity, number> = { conflict: 0, warning: 1, info: 2 }

export function worstFinding(findings: Finding[]): Finding | null {
  let best: Finding | null = null
  for (const f of findings) {
    if (!best || SEVERITY_RANK[f.severity] < SEVERITY_RANK[best.severity]) best = f
  }
  return best
}

/** Short tag for the suggestion card, from the finding kind. */
export const FINDING_TAG: Record<string, string> = {
  expired_cert: 'Expiry',
  missing_doc: 'Missing',
  low_confidence: 'Unread',
  schedule_change: 'Load-in',
  shortage: 'Shortage',
  double_booking: 'Clash',
  over_budget: 'Budget',
  parsed_field: 'Parsed',
  low_capacity: 'Low capacity',
}

export const findingTag = (kind: string) => FINDING_TAG[kind] ?? kind.replace(/_/g, ' ')
