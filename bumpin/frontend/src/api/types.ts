/* Domain types, transcribed from docs/CONTRACT.md sections 2, 3, 7 and 13.
   The backend's handlers return bare `dict`, so FastAPI's OpenAPI schema has no
   response shapes to generate from — these are maintained by hand. If the
   backend ever adds Pydantic response models, replace this file with a
   generated one. */

export type TicketType = 'rider_needs' | 'vendor_eligibility' | 'help'
export type TicketStatus =
  | 'open' | 'needs_review' | 'in_progress' | 'approved' | 'rejected' | 'resolved'
export type Severity = 'conflict' | 'warning' | 'info'
export type FindingKind =
  | 'shortage' | 'double_booking' | 'over_budget'
  | 'expired_cert' | 'missing_doc' | 'low_confidence' | 'schedule_change'
  /* Not problems. A highlight can only come from a finding, so a field Bumpin
     read cleanly is carried as an `info` finding and a field worth a second
     look as a `warning` one. (This used to cite the document pane's three-tone
     legend, which has since been removed from that screen.) */
  | 'parsed_field' | 'low_capacity'
export type FindingStatus = 'open' | 'ignored' | 'resolved'
export type OwnerType = 'artist' | 'vendor'

export interface Finding {
  id: number
  kind: FindingKind
  severity: Severity
  status: FindingStatus
  message: string
  suggestion: string | null
  quote: string | null
  page: number | null
  doc_id: number | null
  bbox: unknown | null
}

export interface DocumentRef {
  id: number
  kind: string
  filename: string
  expiry_date: string | null
  issuer: string | null
}

/** Only `help` tickets carry these. Each is approved or edited on its own. */
export interface ProposedAction {
  index: number
  kind: 'move_set' | 'notify'
  title: string
  detail: string
  to_addr: string | null
  artist_id: number | null
  new_start: string | null
  new_end: string | null
  /** `denied` is a decision too: the action is closed, nothing moved and
   *  no email was drafted. `approved_by` carries whoever decided either way. */
  status: 'proposed' | 'approved' | 'denied'
  approved_by: string | null
  outbox_id: number | null
}

export interface DraftEmail {
  outbox_id: number
  to: string
  subject: string
  body: string
  context_used: string[]
  status: 'draft' | 'sent'
}

/** `GET /tickets` returns these fields — verified against the live response,
 *  which carries more than the contract's section 13 example shows. */
export interface TicketSummary {
  id: number
  type: TicketType
  status: TicketStatus
  severity: Severity
  summary: string
  owner_type: OwnerType
  owner_id: number
  owner: { type: OwnerType; id: number; name: string }
  open_findings: number
  decided_by: string | null
  decided_at: string | null
  created_at: string
  updated_at: string
}

/** What the rider actually asked for, counted off `rider_items`. Null on a
 *  ticket with no rider behind it (vendor tickets), so a screen can tell
 *  "nothing asked for" apart from "nothing to ask". */
export interface Requirements {
  total: number
  technical: number
  hospitality: number
}

export interface TicketDetail extends TicketSummary {
  requirements: Requirements | null
  findings: Finding[]
  documents: DocumentRef[]
  proposed_actions: ProposedAction[] | null
  draft_email: DraftEmail | null
  decided_by: string | null
  decided_at: string | null
}

/** Origin is top-left. Draw `rect` scaled by `rect / page_size`. */
export type Highlight =
  | { type: 'pdf'; page: number; rect: [number, number, number, number]
      page_size: [number, number]; finding_id: number; severity: Severity; status: FindingStatus }
  | { type: 'image'; page: number; rect: [number, number, number, number]
      page_size: [number, number]; finding_id: number; severity: Severity; status: FindingStatus }
  | { type: 'text'; page: number; start: number; end: number
      finding_id: number; severity: Severity; status: FindingStatus }

/** One weekday column of "Card — Intake" 26:2. Seven of these come back, Mon
 *  first, and a day with no mail is three zeroes rather than a missing entry. */
export interface IntakeDay {
  day: string
  clean: number
  flagged: number
  clash: number
}

/** One labelled row of "Card — Hospitality spend" 157:2. `spend` is dollars and
 *  is 0 for any category whose lines carry no `unit_cost` — that is "not
 *  priced", not "nothing spent", so `lines` is the only figure such a row has. */
export interface HospitalityRow {
  name: string
  spend: number
  lines: number
}

export interface Hospitality {
  spend_total: number
  cap_total: number
  rows: HospitalityRow[]
}

/** The five-way split behind "Card — Readiness" 35:2. The buckets partition
 *  every supplier, so they sum to `suppliers.artists + suppliers.vendors`. */
export interface Readiness {
  cleared_rider: number
  cleared_vendor: number
  in_progress: number
  not_started: number
  not_received: number
}

export interface Overview {
  festival: { id: number; name: string; start_date: string; end_date: string; sim_today: string }
  suppliers: {
    artists: number; artists_scheduled: number; artists_applied: number
    artists_ready: number; vendors: number; vendors_ready: number
  }
  readiness_pct: number
  documents: number
  needing_attention: number
  expiring_soon: number
  open_conflicts: number
  /* The three dashboard-card fields are optional because the backend is still
     moving under this screen; each card falls back to its empty specimen when
     its field is absent rather than taking the whole dashboard down. */
  intake?: IntakeDay[]
  hospitality?: Hospitality
  readiness?: Readiness
}

export interface Artist {
  id: number; name: string; manager_name: string; manager_email: string
  stage_id: number | null; stage_name: string | null
  set_start: string | null; set_end: string | null
  status: 'applied' | 'in_progress' | 'completed'
  hospitality_cap: number | null
}

export interface Vendor {
  id: number; name: string; type: 'food' | 'beverage' | 'merch' | 'other'
  contact_name: string; contact_email: string
  uses_gas: boolean; site_zone: string
  load_in_start: string; load_in_end: string
  status: 'in_progress' | 'completed' | 'rejected'
  document_count: number
  earliest_expiry: string | null
  latest_ticket_id: number | null
  latest_ticket_status: TicketStatus | null
}

export interface Stage {
  id: number; name: string; location: string | null
}

export interface Allocation {
  artist_id: number; artist_name?: string
  quantity: number; start_ts: string; end_ts: string
}

export interface InventoryItem {
  id: number; stage_id: number | null; stage_name: string | null
  canonical_name: string; category: string
  quantity_total: number
  aliases: string[]
  allocations: Allocation[]
}

export interface RunsheetRow {
  day: string; start: string; end: string
  area: string; who: string
  kind: 'set' | 'load_in'
  status: string
  contact: string | null
  /** Which artist the row IS, so it can be taken back off the sheet. Null on a
   *  vendor load-in: that window lives on the vendor and moves by approving the
   *  vendor's ticket, so the run sheet has no business deleting it. */
  artist_id: number | null
}

/** Body of `POST /inventory`, which answers with the created `InventoryItem`.
 *  `stage_id` null is the shared pool. Aliases are not part of it: they exist so
 *  the rider parser can match an artist's wording, and a row typed by hand has
 *  no wording to match. */
export interface NewInventoryItem {
  canonical_name: string; category: string
  stage_id: number | null; quantity_total: number | null
}

/** Body of `POST /runsheet/sets`, which answers with the created `RunsheetRow`.
 *  `start` and `end` are naive local timestamps — the same form every other
 *  timestamp in the schedule takes, and what an `<input type="datetime-local">`
 *  already produces. */
export interface NewSet {
  /** Null is a control the operator has not filled in — a state the form can
   *  genuinely be in, and the endpoint names the field rather than guessing. */
  artist_id: number | null; stage_id: number | null
  start: string; end: string
}

export interface OutboxRow {
  id: number; ticket_id: number | null
  to_addr: string; subject: string; body: string
  context_used: string[]
  status: 'draft' | 'sent' | 'failed'
  created_by: string; approved_by: string | null
  sent_at: string | null; mode: string
}

export interface Notification {
  id: number; for_user: string; ticket_id: number
  text: string; created_at: string; seen: boolean
}

export interface PhoneCard {
  id: string; ticket_id: number
  urgency: 'high' | 'medium' | 'low'
  reason: 'major_change' | 'needs_review' | 'pending_approval'
  title: string; summary: string; snippet: string
  actions: string[]
  finding_ids: number[]
  created_at: string
}

export interface InboundEmail {
  from: string; subject: string; body: string; attachments: string[]
}

export interface InboxResult {
  email_id: number
  ticket_id: number
  ticket_type: TicketType
  ticket_status: TicketStatus
  routing: 'auto_filed' | 'needs_review'
  confidence_band: 'auto' | 'review' | 'review_top'
  notified_ravi: boolean
  is_major_change: boolean
  classification: unknown
}
