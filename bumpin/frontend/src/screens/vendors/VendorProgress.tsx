import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { TopBar } from '@/components/AppShell'
import { EmptyState, Stat, StatStrip } from '@/components/primitives'
import { matches, useSearch } from '@/components/search'
import { api } from '@/api/client'
import type { Overview } from '@/api/types'
import {
  CERT_GROUPS, SORTS, buildBoard, conflictsOf, initials, sortCards,
  type BoardCard, type ConflictTally, type CertGroup, type SortId, type VendorWithDocuments,
} from './vendorModel'
import s from './vendors.module.css'

/** Figma 159:2 — "Bumpin — Vendor progress".
 *
 *  Screen 159:8, canvas 159:33 (pad 40, gap 28): top bar 159:34, controls
 *  159:46, board 159:74. Columns are 216 wide on a 22px gutter with a 98px
 *  "add" column closing the row (5*216 + 98 + 5*22 = 1288).
 *
 *  Cards are tinted by whether the paperwork is still valid on event day:
 *  blue 159:456, pink 159:472, yellow 159:488. The stat strip counts those
 *  tints — in the design 6 awaiting / 4 conflict / 10 valid is exactly the
 *  tally of yellow / pink / blue cards on the board. */
export function VendorProgress() {
  const [vendors, setVendors] = useState<VendorWithDocuments[] | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sort, setSort] = useState<SortId>('status')
  const [conflicts, setConflicts] = useState<ReadonlyMap<number, ConflictTally | null>>(new Map())
  const { q } = useSearch()

  useEffect(() => {
    let live = true
    ;(async () => {
      try {
        const [ov, rows] = await Promise.all([api.overview(), api.vendors()])
        // `GET /vendors` carries no documents; the board needs each vendor's
        // document kinds, so the detail rows are pulled alongside.
        const full = await Promise.all(
          rows.map((v) => api.vendor(v.id) as Promise<VendorWithDocuments>),
        )
        if (!live) return
        setOverview(ov)
        setVendors(full)
        /* The bar counts conflicts on the vendor's ticket, and only the detail
           route carries findings — `GET /vendors` stops at `latest_ticket_id`.
           A second pass, so the board paints before the bars fill, and a
           failed detail leaves that one ticket unknown rather than the board. */
        const ids = [...new Set(full.map((v) => v.latest_ticket_id).filter((id): id is number => id !== null))]
        const pairs = await Promise.all(ids.map(async (id) => {
          try { return [id, conflictsOf((await api.ticket(id)).findings)] as const }
          catch { return [id, null] as const }
        }))
        if (live) setConflicts(new Map(pairs))
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : 'Could not load vendors.')
      }
    })()
    return () => { live = false }
  }, [])

  const festivalEnd = overview?.festival.end_date ?? null

  const board = useMemo(
    () => (vendors && festivalEnd ? buildBoard(vendors, festivalEnd, conflicts) : null),
    [vendors, festivalEnd, conflicts],
  )

  const query = q.trim()

  /* Search narrows, sort reorders, and they compose because the filter runs
     first and the sort runs over whatever survived it. `board` itself is never
     narrowed, so the stat strip and the whole-board empty state below still see
     every card. */
  const columns = useMemo(() => {
    if (!board) return null
    let shown = 0
    const out = CERT_GROUPS.map((group) => {
      const all = board.byGroup.get(group.id) ?? []
      const cards = sortCards(all.filter((c) => matches(query, c.vendor.name, c.title)), sort)
      shown += cards.length
      return { group, cards, filteredOut: all.length > 0 && cards.length === 0 }
    })
    return { out, shown }
  }, [board, query, sort])

  return (
    <>
      <TopBar title="Vendor progress" placeholder="Search vendors and certificates" />

      {/* 159:46 Controls */}
      <div className={s.controls}>
        <SortControl value={sort} onChange={setSort} />
        {/* 159:61 Stats — gap 32, rules yellow / pink / blue. These count the
            whole board on purpose: they are the festival's readiness, not a
            running total of whatever is typed in the search box. */}
        <StatStrip>
          <Stat label="Awaiting" value={board ? board.counts.awaiting : '—'} rule="yellow" />
          <Stat label="Conflict" value={board ? board.counts.conflict : '—'} rule="pink" />
          <Stat label="Valid" value={board ? board.counts.valid : '—'} rule="blue" />
        </StatStrip>
      </div>

      {error && <p className={`${s.error} t-body-sm`}>{error}</p>}

      {!board && !error && <p className={`${s.loading} t-body-md`}>Reading the document board…</p>}

      {board && columns && (
        <>
          {/* Said out loud because the strip above disagrees with the board
              while a query is active, and a silent disagreement reads as a bug. */}
          {query !== '' && (
            <p className={`${s.filterNote} t-body-sm`}>
              Showing {columns.shown} of {board.total} cards matching “{query}”. The counts above
              still cover the whole board.
            </p>
          )}

          <div className={s.board}>
            {columns.out.map(({ group, cards, filteredOut }) => (
              <section key={group.id} className={s.column} aria-label={group.label}>
                <div className={s.columnRule} aria-hidden />
                <header className={s.columnHead}>
                  <h2 className={`${s.columnHeadLabel} t-label-md`}>{group.label}</h2>
                  <span className={s.plus} aria-hidden />
                </header>
                {cards.length === 0 ? (
                  <p className={`${s.columnEmpty} t-caption`}>{columnNote(group, filteredOut)}</p>
                ) : (
                  cards.map((card) => <BoardCardTile key={card.key} card={card} />)
                )}
              </section>
            ))}
            {/* 159:407 Column — Add: rule plus a right-aligned glyph, 98 wide */}
            <div className={`${s.column} ${s.columnAdd}`} aria-hidden>
              <div className={s.columnRule} />
              <div className={`${s.columnHead} ${s.columnHeadAdd}`}>
                <span className={s.plus} />
              </div>
            </div>
          </div>

          {/* `board.total`, not the filtered count: "no paperwork yet" is a
              statement about the festival, and a search that matches nothing
              must not make it. */}
          {board.total === 0 && (
            <EmptyState
              title="No vendor paperwork yet"
              body="Documents land here once a vendor emails them in."
            />
          )}

          {board.unfiled.length > 0 && (
            <p className={`${s.unfiled} t-body-sm`}>
              {board.unfiled.length} document{board.unfiled.length === 1 ? '' : 's'} has a kind no
              column covers ({[...new Set(board.unfiled.map((u) => u.doc.kind))].join(', ')}).
            </p>
          )}
        </>
      )}
    </>
  )
}

/** Three different empty columns, and conflating them loses information:
 *  nothing can ever land here, nothing has been filed yet, or the search hid
 *  what is filed. */
function columnNote(group: CertGroup, filteredOut: boolean) {
  if (group.kinds.length === 0) return 'No document kind maps here'
  if (filteredOut) return 'No matches in this column'
  return 'Nothing filed'
}

/** 101:7 — a 9x4.5 chevron in a 10x6 box, stroke #7a7161, 1.5, round caps.
 *  Transcribed from the rider board rather than imported: the slice folders do
 *  not reach across each other. */
const Chevron = () => (
  <svg className={s.chevron} width="10" height="6" viewBox="-0.5 -0.8 10 6" fill="none"
       stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden>
    <path d="M 0 0 L 4.5 4.5 L 9 0" />
  </svg>
)

/** Replaces the old Vendors/Riders segmented pair in 159:48 — the nav rail
 *  already reaches the rider board, so that control only ever duplicated it.
 *
 *  Shaped like the rider board's `Control` (101:4, `Label: Value` + chevron) so
 *  the two boards' control rows line up, but this one is a real listbox: focus
 *  sits on the list and `aria-activedescendant` names the highlighted row, which
 *  is the pattern a native select exposes. The rows are therefore options, not
 *  buttons. */
function SortControl({ value, onChange }: { value: SortId; onChange: (v: SortId) => void }) {
  const [open, setOpen] = useState(false)
  const [cursor, setCursor] = useState(() => SORTS.findIndex((o) => o.id === value))
  const wrap = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    list.current?.focus()
    // pointerdown, not click: a press on a board card should dismiss the menu
    // and still let the card's own click through to the router.
    const away = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', away)
    return () => document.removeEventListener('pointerdown', away)
  }, [open])

  const current = SORTS.find((o) => o.id === value) ?? SORTS[0]
  const at = SORTS[cursor] ?? current

  const reveal = () => {
    setCursor(Math.max(0, SORTS.findIndex((o) => o.id === value)))
    setOpen(true)
  }
  const dismiss = () => { setOpen(false); trigger.current?.focus() }
  const choose = (i: number) => { onChange(SORTS[i].id); dismiss() }

  return (
    <div className={s.sortWrap} ref={wrap}>
      <button type="button" ref={trigger}
              className={`${s.control} ${open ? s.controlOpen : ''} t-label-md`}
              aria-haspopup="listbox" aria-expanded={open}
              aria-controls={open ? 'vendor-sort-list' : undefined}
              onClick={() => (open ? setOpen(false) : reveal())}
              onKeyDown={(e) => {
                // Enter and Space already click a button; the arrows have to be
                // wired by hand, and must not scroll the board instead.
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); reveal() }
              }}>
        Sort: {current.label}
        <Chevron />
      </button>

      {open && (
        <ul id="vendor-sort-list" ref={list} className={s.menu} role="listbox" tabIndex={-1}
            aria-label="Sort vendor cards" aria-activedescendant={`vendor-sort-${at.id}`}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault(); setCursor((i) => (i + 1) % SORTS.length)
              } else if (e.key === 'ArrowUp') {
                e.preventDefault(); setCursor((i) => (i - 1 + SORTS.length) % SORTS.length)
              } else if (e.key === 'Home') {
                e.preventDefault(); setCursor(0)
              } else if (e.key === 'End') {
                e.preventDefault(); setCursor(SORTS.length - 1)
              } else if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault(); choose(cursor)
              } else if (e.key === 'Escape') {
                e.preventDefault(); dismiss()
              } else if (e.key === 'Tab') {
                // Let the browser move on, but do not leave the menu hanging.
                setOpen(false)
              }
            }}>
          {SORTS.map((o, i) => (
            <li key={o.id} id={`vendor-sort-${o.id}`} role="option"
                aria-selected={o.id === value}
                className={`${s.option} ${i === cursor ? s.optionCursor : ''} t-label-md`}
                // Keeps focus on the list, so the keyboard still drives the menu
                // after a mouse user has hovered through it.
                onPointerDown={(e) => e.preventDefault()}
                onPointerEnter={() => setCursor(i)}
                onClick={() => choose(i)}>
              <span className={`${s.optionDot} ${o.id === value ? s.optionDotOn : ''}`} aria-hidden />
              {o.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** 159:456 Card — r 24, pad 20, VERTICAL gap 16, shadow-card, no stroke. */
function BoardCardTile({ card }: { card: BoardCard }) {
  return (
    <Link
      to={`/vendors/${card.vendor.id}`}
      className={`${s.bcard} ${s[`bcard_${card.tone}`]}`}
      aria-label={`${card.vendor.name} · ${card.title}`}
    >
      {/* 159:457 Title row */}
      <div className={s.bcardTitleRow}>
        <h3 className={`${s.bcardTitle} t-heading-sm`}>{card.title}</h3>
        <span className={s.bcardMore} aria-hidden>•••</span>
      </div>

      {/* 159:460 Progress. The design draws five fixed segments; what they
          count is the vendor ticket's conflicts, so the number of segments is
          the number raised and a filled one (#1a1614) is a conflict dealt
          with. No conflicts means no denominator, so no track is drawn — an
          empty track would read as "none of them done". */}
      {card.conflicts === null && card.vendor.latest_ticket_id ? (
        <p className={`${s.noConflicts} t-caption`}>Counting conflicts…</p>
      ) : card.conflicts === null || card.conflicts.raised === 0 ? null : (
        <div
          className={s.progress}
          role="img"
          aria-label={`${card.conflicts.resolved} of ${card.conflicts.raised} conflicts resolved`}
        >
          {Array.from({ length: card.conflicts.raised }, (_, i) => (
            <span
              key={i}
              className={`${s.progressSeg} ${i < card.conflicts!.resolved ? s.progressSegOn : ''}`}
            />
          ))}
        </div>
      )}

      {/* 159:466 Footer */}
      <div className={s.bcardFooter}>
        <span className={`${s.bcardAvatar} t-label-sm`} aria-hidden>
          {initials(card.vendor.name)}
        </span>
        <span className={s.bcardMeta}>
          <span className={`${s.bcardVendor} t-body-md-b`}>{card.vendor.name}</span>
          {card.date && <span className={`${s.bcardDate} t-body-sm`}>{card.date}</span>}
        </span>
      </div>
    </Link>
  )
}
