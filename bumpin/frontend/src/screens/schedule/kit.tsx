import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, StatStrip } from '@/components/primitives'
import s from './schedule.module.css'

/* The anatomy the Run sheet and Equipment screens share. Only these two
   screens use it, so it lives here rather than in components/primitives. */

/* ------------------------------------------------------------- fetching -- */

export type Resource<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: T }

/** `load` must be a stable reference — pass `api.runsheet`, not a closure.
 *  The second element refetches, for after a row has been written. */
export function useResource<T>(load: () => Promise<T>): [Resource<T>, () => void] {
  const [state, setState] = useState<Resource<T>>({ status: 'loading' })
  const [refetches, setRefetches] = useState(0)
  useEffect(() => {
    let live = true
    /* A refetch leaves the rows on screen while it is in flight. Blanking the
       table back to "Loading…" the moment a row is added would read as though
       the add had thrown the table away. The first load has nothing to keep,
       and `load` never changes — the contract above is that it is stable. */
    if (refetches === 0) setState({ status: 'loading' })
    load().then(
      (data) => { if (live) setState({ status: 'ready', data }) },
      (err: unknown) => {
        if (live) setState({
          status: 'error',
          message: err instanceof Error ? err.message : String(err),
        })
      },
    )
    return () => { live = false }
  }, [load, refetches])
  return [state, useCallback(() => setRefetches((n) => n + 1), [])]
}

/* --------------------------------------------------------------- chrome -- */

/** Figma 212:418 / 224:184 — filters on the left, the stat strip on the
 *  right, bottom edges aligned. */
export function ControlsRow({ left, stats }: { left: ReactNode; stats: ReactNode }) {
  return (
    <div className={s.controls}>
      <div className={s.controlsLeft}>{left}</div>
      <StatStrip>{stats}</StatStrip>
    </div>
  )
}

/** Figma 214:2 / 224:206 — the card plus its title block. The Card primitive
 *  carries the surface (white, 1px #e4dece, radius 24, 0 2 10 #12141f/6%,
 *  26/28/28 padding); the title block is spaced by hand because the design
 *  puts the sub 2px under the title and the header row 26px under that. */
export function TableCard({ title, sub, note, cols, form, children }: {
  title: string
  sub: string
  /** Not in the design: what the top-bar search is currently hiding. */
  note?: ReactNode
  cols: string
  /** Not in the design either — the open AddPanel, which sits inside the card so
   *  it is attached to the table it writes to rather than floating above it. */
  form?: ReactNode
  children: ReactNode
}) {
  return (
    <Card className={cols}>
      <div className={s.head}>
        <h2 className={`${s.headTitle} t-heading-sm`}>{title}</h2>
        <p className={`${s.headSub} t-caption`}>{sub}</p>
        {note && <p className={`${s.headNote} t-caption`} role="status">{note}</p>}
      </div>
      {form}
      {children}
    </Card>
  )
}

/* ---------------------------------------------------------------- cells -- */

export const Cell = ({ className = '', children }: { className?: string; children?: ReactNode }) =>
  <span className={`${s.cell} ${className}`} role="cell">{children}</span>

/** 14/20 Regular at #1a1614 — Figma 216:9. */
export const Plain = ({ children }: { children: ReactNode }) =>
  <Cell className={`${s.ink} t-body-sm`}>{children}</Cell>

/** 14/20 Medium at #1a1614 — the name column, Figma 216:10. */
export const Name = ({ children }: { children: ReactNode }) =>
  <Cell className={`${s.ink} t-label-md`}>{children}</Cell>

/** 12/16 Regular at #7a7161 — Figma 216:16. */
export const Quiet = ({ children }: { children: ReactNode }) =>
  <Cell className={`${s.quiet} t-caption`}>{children}</Cell>

/** Figma 228:65 — a cell with nothing in it is an em dash at #b5ac99. */
export const Nothing = () =>
  <Cell className={`${s.none} t-body-sm`}>—</Cell>

/** A cell that carries a chip, which must not be clipped by the ellipsis. */
export const ChipCell = ({ className = '', children }: { className?: string; children?: ReactNode }) =>
  <span className={className} role="cell">{children}</span>

/** The minus at the end of a row.
 *
 *  Not in the design: 212:2 and 224:147 are read-only tables. It exists because
 *  the add panels above it made rows that can be typed wrong, and the only way
 *  back was SQL. Rows the screen does not own render the cell empty rather than
 *  a disabled button — a vendor load-in is not a run sheet row that happens to
 *  be locked, it is somebody else's record showing through. */
export function RemoveCell({ onRemove, label, busy }: {
  /** Omitted when this row is not the screen's to remove. */
  onRemove?: () => void
  label: string
  busy?: boolean
}) {
  if (!onRemove) return <span className={s.removeCell} role="cell" />
  return (
    <span className={s.removeCell} role="cell">
      <button type="button" className={s.remove} onClick={onRemove}
              disabled={busy} aria-label={label} title={label}>
        {/* A drawn rule rather than a hyphen or a minus glyph, which both sit
            off-centre in this font at this size. */}
        <svg width="10" height="2" viewBox="0 0 10 2" aria-hidden>
          <rect width="10" height="2" rx="1" fill="currentColor" />
        </svg>
      </button>
    </span>
  )
}

/* ---------------------------------------------------------------- empty -- */

/** Figma 231:1312, transcribed from the node's own vectorPaths. */
const UploadGlyph = () => (
  <svg
    className={s.emptyGlyph}
    width="32" height="22" viewBox="0 0 32 22"
    fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
    aria-hidden
  >
    <path d="M 0 14 L 0 22 L 32 22 L 32 14 M 16 18 L 16 0 M 16 0 L 8 8 M 16 0 L 24 8" />
  </svg>
)

/** Figma 231:1311 — the "Table — nothing uploaded" specimen, shown below the
 *  header row so the columns stay readable while the table is empty. */
export function TableEmpty() {
  const navigate = useNavigate()
  return (
    <div className={s.empty}>
      <UploadGlyph />
      <p className={`${s.emptyTitle} t-heading-sm`}>Nothing to show yet</p>
      <p className={`${s.emptyBody} t-body-md`}>
        Upload a rider sheet, a vendor list or a stage equipment manifest to fill this in.
      </p>
      <Button onClick={() => navigate('/upload')}>Go to Upload</Button>
    </div>
  )
}

/** The same block without the action, for the states the design does not
 *  specify: the first paint and a failed request. */
export function TableNotice({ title, body }: { title: string; body?: string }) {
  return (
    <div className={s.empty}>
      <p className={`${s.emptyTitle} t-heading-sm`}>{title}</p>
      {body && <p className={`${s.emptyBody} t-body-md`}>{body}</p>}
    </div>
  )
}

/** A table emptied by the top-bar search, which is not the same thing as a
 *  table with nothing in it — so it carries neither the upload glyph nor the
 *  "Go to Upload" button that TableEmpty offers. */
export function TableNoMatches({ query, noun }: { query: string; noun: string }) {
  return (
    <TableNotice
      title={`No ${noun} match this search`}
      body={`Nothing here matches \u201c${query.trim()}\u201d. Clear the search to see everything again.`}
    />
  )
}

/* --------------------------------------------------------------- adding -- */

/** What a control the operator has not filled in should send.
 *
 *  Not `Number(value)`: `Number('')` is 0, a perfectly good integer, so an
 *  untouched Stage select would reach the endpoint as stage 0 and be refused
 *  with "That stage is not on file" — about a stage nobody picked. null is the
 *  honest "unset", and the endpoint answers it with "Pick a stage." */
export const entered = (value: string): number | null =>
  value === '' ? null : Number(value)

/** The chrome around a new row's fields.
 *
 *  Nothing in the design adds a row — 212:2 and 224:147 are read-only tables —
 *  so this is assembled out of parts that ARE drawn: the sunken surface of the
 *  email body box (204:353) and the field stack of the edit popover (203:17..21).
 *
 *  There is no client-side copy of the rules. The endpoint is the only thing
 *  that can refuse a row, and it answers with the sentence to show, so a second
 *  set of checks here could only ever disagree with the one that matters. */
export function AddPanel({ title, submit, error, busy, onSubmit, onCancel, children }: {
  title: string
  submit: string
  error: string | null
  busy: boolean
  onSubmit: () => void
  onCancel: () => void
  children: ReactNode
}) {
  return (
    <form
      className={s.panel}
      /* The browser's own bubble would say something different from the message
         under the fields, and would say it before the request that decides. */
      noValidate
      onSubmit={(e) => { e.preventDefault(); onSubmit() }}
    >
      <p className={`${s.panelTitle} t-label-md`}>{title}</p>
      <div className={s.panelFields}>{children}</div>
      {/* A refusal has to be announced, not only drawn: the field that caused it
          is not always the one the operator is looking at. */}
      {error !== null && <p className={`${s.panelError} t-body-sm`} role="alert">{error}</p>}
      <div className={s.panelFoot}>
        <Button type="submit" disabled={busy}>{busy ? 'Adding…' : submit}</Button>
        <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

/** Figma 203:19 / 203:20 — one labelled control, the label 6px above it. `grow`
 *  is the flex weight, so an item name can take more of the row than a total. */
export function Field({ label, grow = 1, children }: {
  label: string
  grow?: number
  children: ReactNode
}) {
  return (
    <label className={s.field} style={{ flexGrow: grow }}>
      <span className={`${s.fieldLabel} t-label-sm`}>{label}</span>
      {children}
    </label>
  )
}

export const cols = { runsheet: s.runsheetCols, equipment: s.equipmentCols }
/** Figma 203:21, inverted — see the note in schedule.module.css. */
export const control = s.control
export const freeChip = s.freeChip
/** The card's note slot, in the refusal's colour. */
export const rowNote = s.removeError
export const tabs = s.tabs
