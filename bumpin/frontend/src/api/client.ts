import type {
  Artist, Highlight, InboundEmail, InboxResult, InventoryItem, NewInventoryItem,
  NewSet, Notification, OutboxRow, Overview, PhoneCard, RunsheetRow, Stage,
  TicketDetail, TicketSummary, Vendor,
} from './types'

/** Single-operator build: Ravi is always the actor. The backend requires the
 *  header on every mutating call but does not care who sends it. */
export const ACTOR = 'ravi'

const BASE = '/api'

/** A 409 from an already-decided ticket carries who decided and when at the top
 *  level; a 409 from an approve blocked by an open conflict carries only detail. */
export class ApiError extends Error {
  status: number
  detail: string
  decidedBy?: string
  decidedAt?: string

  constructor(status: number, payload: Record<string, unknown>) {
    const detail = typeof payload.detail === 'string' ? payload.detail : `HTTP ${status}`
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    if (typeof payload.decided_by === 'string') this.decidedBy = payload.decided_by
    if (typeof payload.decided_at === 'string') this.decidedAt = payload.decided_at
  }

  /** True when the ticket was already decided by someone else. */
  get isAlreadyDecided() {
    return this.status === 409 && this.decidedBy !== undefined
  }

  /** True when an approve was refused because a conflict is still open. */
  get isBlockedByConflict() {
    return this.status === 409 && this.decidedBy === undefined
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-User': ACTOR,
      ...(init?.headers ?? {}),
    },
  })
  if (!res.ok) {
    let payload: Record<string, unknown> = {}
    try {
      payload = await res.json()
    } catch {
      // non-JSON error body; fall through with an empty payload
    }
    throw new ApiError(res.status, payload)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const get = <T>(path: string) => req<T>(path)
const post = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const patch = <T>(path: string, body: unknown) =>
  req<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
const del = <T>(path: string) => req<T>(path, { method: 'DELETE' })

const qs = (params: Record<string, string | number | boolean | undefined>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined) p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const api = {
  health: () => get<{ ok: boolean; festival: string }>('/health'),
  overview: () => get<Overview>('/overview'),
  demoReset: () => post<unknown>('/demo/reset'),

  artists: () => get<Artist[]>('/artists'),
  vendors: (f: { type?: string; status?: string } = {}) => get<Vendor[]>('/vendors' + qs(f)),
  vendor: (id: number) => get<Vendor & { documents: unknown[] }>(`/vendors/${id}`),
  stages: () => get<Stage[]>('/stages'),
  inventory: () => get<InventoryItem[]>('/inventory'),
  runsheet: () => get<RunsheetRow[]>('/runsheet'),

  /** The two schedule writers. Each answers with the created row in exactly the
   *  shape its own GET sends, and refuses with a 422 (bad field) or 409 (a row
   *  that already exists, or a stage already taken) whose `detail` is one
   *  sentence meant to be shown to the operator as it is. */
  addInventoryItem: (body: NewInventoryItem) => post<InventoryItem>('/inventory', body),
  addSet: (body: NewSet) => post<RunsheetRow>('/runsheet/sets', body),
  /* The mirror of the two above. Both refuse anything an approved rider is
     standing on, so the refusal is a sentence worth showing, not a 500. */
  removeInventoryItem: (id: number) => del<{ ok: true }>(`/inventory/${id}`),
  removeSet: (artistId: number) => del<{ ok: true }>(`/runsheet/sets/${artistId}`),

  tickets: (f: { type?: string; status?: string } = {}) => get<TicketSummary[]>('/tickets' + qs(f)),
  ticket: (id: number) => get<TicketDetail>(`/tickets/${id}`),

  // Every ticket action returns the fresh ticket detail.
  approve: (id: number, overrideReason?: string) =>
    post<TicketDetail>(`/tickets/${id}/approve`, overrideReason ? { override_reason: overrideReason } : {}),
  reject: (id: number, reason: string) => post<TicketDetail>(`/tickets/${id}/reject`, { reason }),
  resolveFinding: (id: number, findingId: number) =>
    post<TicketDetail>(`/tickets/${id}/findings/${findingId}/resolve`),
  ignoreFinding: (id: number, findingId: number) =>
    post<TicketDetail>(`/tickets/${id}/findings/${findingId}/ignore`),

  /** Approving one action writes the schedule change immediately and drafts one
   *  email. It does not send. Refetch anything schedule-shaped afterwards. */
  approveAction: (id: number, index: number) =>
    post<TicketDetail>(`/tickets/${id}/actions/${index}/approve`),
  denyAction: (id: number, index: number) =>
    post<TicketDetail>(`/tickets/${id}/actions/${index}/deny`),
  editAction: (id: number, index: number, edits: Record<string, string>) =>
    post<TicketDetail>(`/tickets/${id}/actions/${index}/edit`, edits),

  outbox: (f: { status?: string; ticket_id?: number } = {}) => get<OutboxRow[]>('/outbox' + qs(f)),
  updateDraft: (id: number, body: { subject?: string; body?: string }) =>
    patch<OutboxRow>(`/outbox/${id}`, body),
  send: (id: number) => post<OutboxRow>(`/outbox/${id}/send`),

  notifications: (unseenOnly = false) =>
    get<Notification[]>('/notifications' + qs({ user: ACTOR, unseen_only: unseenOnly })),
  markSeen: (id: number) => post<unknown>(`/notifications/${id}/seen`),

  phoneCards: () => get<PhoneCard[]>('/phone/cards' + qs({ user: ACTOR })),

  highlights: (docId: number) => get<Highlight[]>(`/documents/${docId}/highlights`),
  inboxReceive: (msg: InboundEmail) => post<InboxResult>('/inbox/receive', msg),
}

/** Served as bytes, not JSON — use these directly as src/href. */
export const urls = {
  documentFile: (docId: number) => `${BASE}/documents/${docId}/file`,
  runsheetXlsx: `${BASE}/export/runsheet.xlsx`,
}
