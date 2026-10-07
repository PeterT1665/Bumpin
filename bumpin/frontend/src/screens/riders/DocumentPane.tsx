import {
  useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode,
} from 'react'
import { urls } from '@/api/client'
import type { Highlight, Severity } from '@/api/types'
import { HIGHLIGHT_TONE } from './riders'
import s from './DocumentPane.module.css'

/* Figma 119:2 "Source document" plus 121:11 "Pages".
 *
 * One pane renders all three highlight shapes that
 * `GET /documents/{id}/highlights` can return:
 *
 *   pdf    rect in PDF points   + page_size -> box at rect / page_size
 *   image  rect in image pixels + page_size -> the same proportional maths
 *   text   start / end are character offsets into
 *          `GET /documents/{id}/file` -> underline that span
 *
 * Origin is top-left in all three cases. Only `severity: "conflict"` reads as a
 * conflict, and it reads as soft pink with dark text — there is no red here.
 * Entries whose `status` is not `open` are dropped. */

export type DocKind = 'pdf' | 'image' | 'text' | 'unknown'

export type BoxHighlight = Extract<Highlight, { rect: [number, number, number, number] }>
export type TextHighlight = Extract<Highlight, { start: number }>

const isBox = (h: Highlight): h is BoxHighlight => h.type === 'pdf' || h.type === 'image'
const isText = (h: Highlight): h is TextHighlight => h.type === 'text'

/** The visual outset of a highlight over its text, read off 119:29 against
 *  119:28: the box is 5px wider either side and 3px taller top and bottom than
 *  the 20px line it covers, with a flush 2px underline below it. */
const PAD_X = 5
const PAD_Y = 3
const RULE = 2
/** The one spacing value not in Figma: the two specimen cards sit ABOVE their
 *  highlights by 17px (191:2) and 53px (121:2), which disagree, and the brief
 *  says the card is anchored UNDER the line. 8px is this file's choice. */
const ANCHOR_GAP = 8
/** The card's top-left sits just past the highlight's bottom-right, the way
 *  Grammarly's does, rather than out at the pane's right edge. */
const CARD_DX = 4
/** Long enough for the pointer to cross the gap from highlight to card without
 *  the card closing underneath it. */
const CLOSE_MS = 180

export type Quote = { findingId: number; quote: string; severity: Severity }

/** Hover opens, click pins. Every card here hangs off a highlight, so these are
 *  the only ways in. */
type HighlightHandlers = {
  onClick: () => void
  onMouseEnter: () => void
  onMouseLeave: () => void
  onFocus: () => void
  onBlur: () => void
  'aria-expanded': boolean
}

type Register = (findingId: number, el: HTMLElement | null) => void

export function DocumentPane({
  docId, kind, highlights, header, page, onPage, onSelect,
  text, anchored, documents = [], onDocument,
}: {
  docId: number | null
  /** Every document on the ticket. When there is more than one, the strip at
   *  the bottom steps through FILES rather than pages — which is what that
   *  strip is for, and what the vendor pane already does. An artist who sends
   *  a page plus an addendum has a conflict on each, and this is the only way
   *  to reach the second. */
  documents?: { id: number; filename: string }[]
  onDocument?: (id: number) => void
  kind: DocKind
  highlights: Highlight[]
  /** 119:3 is an overline; the email meta on 231:2 is plain 12/16 caption. */
  header?: { line1: string; line1Overline?: boolean; line2?: string; subject?: string }
  page: number
  onPage: (p: number) => void
  onSelect: (findingId: number) => void
  /** Already fetched by the caller for `text` documents. */
  text: string | null
  /* A function form so a card can close itself — the warning card's
     acknowledgement has nothing to write, it only needs to put the card away. */
  anchored?: ReactNode | ((dismiss: () => void) => ReactNode)
}) {
  /* EVERY highlight is drawn, including the ones already dealt with — they
     just go inert and faint (see `.boxCleared`). Filtering to `open` meant a
     single click on Ignore or on a warning's acknowledgement wiped the box off
     the page, so the one thing the operator was pointing at vanished and the
     document went back to looking unread. A finding that has been settled is
     still a thing that was found there. */
  const open = useMemo(() => highlights.filter((h) => h.status === 'open'), [highlights])
  const boxes = useMemo(() => highlights.filter(isBox).filter((h) => h.page === page), [highlights, page])
  const spans = useMemo(() => highlights.filter(isText), [highlights])

  const pageCount = useMemo(
    () => Math.max(1, ...highlights.map((h) => h.page), 1),
    [highlights],
  )

  /* ---- hover-anchored card, pinned on click ---- */

  /* Two sources, one card. Hover is transient; a pin outlives the pointer, which
     is what makes a card carrying Approve buttons and an edit form usable at all
     — reaching for a text input must not dismiss the thing holding it. The pin
     also wins over hover while it is set, so crossing a second highlight cannot
     swap the card out from under an edit in progress. */
  const [hoverId, setHoverId] = useState<number | null>(null)
  const [pinnedId, setPinnedId] = useState<number | null>(null)
  const openId = pinnedId ?? hoverId
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  /** One entry per rendered highlight, whichever shape it is, so the card can be
     measured off the real element instead of recomputing the page maths. */
  const anchorEls = useRef(new Map<number, HTMLElement>())
  const stageRef = useRef<HTMLDivElement | null>(null)
  const boundsRef = useRef<HTMLDivElement | null>(null)
  const cardRef = useRef<HTMLDivElement | null>(null)
  const closeTimer = useRef<number | null>(null)
  const [remeasure, setRemeasure] = useState(0)

  const register = useCallback<Register>((findingId, el) => {
    if (el) anchorEls.current.set(findingId, el)
    else anchorEls.current.delete(findingId)
  }, [])

  const cancelClose = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
  }, [])

  /** The highlight Escape was pressed on, while the pointer is still sitting on
   *  it. Unmounting the card changes what is under a stationary pointer, and
   *  Chrome answers that with a fresh mouseover — which re-opens the card in the
   *  same frame it was dismissed. Hold that one highlight shut until the pointer
   *  genuinely leaves it. */
  const suppressed = useRef<number | null>(null)

  const openCard = useCallback((findingId: number) => {
    cancelClose()
    if (pinnedId !== null) return        // a pinned card owns the pane until dismissed
    if (suppressed.current === findingId) return
    setHoverId(findingId)
    onSelect(findingId)
  }, [cancelClose, pinnedId, onSelect])

  const pinCard = useCallback((findingId: number) => {
    cancelClose()
    setPinnedId(findingId)
    setHoverId(findingId)
    onSelect(findingId)
  }, [cancelClose, onSelect])

  /** Escape and an outside click are the only exits once pinned, so both clear
   *  the hover too: otherwise the pointer still resting on the highlight would
   *  re-open the card it was just asked to put away. */
  const dismiss = useCallback(() => {
    cancelClose()
    const el = openId === null ? null : anchorEls.current.get(openId)
    suppressed.current = el?.matches(':hover') ? openId : null
    setPinnedId(null)
    setHoverId(null)
  }, [cancelClose, openId])

  /* The pointer has to be able to travel from the highlight into the card, so
     leaving either only *schedules* the close and entering the other cancels it.
     This touches the hover alone — a pinned card is unmoved by pointer-out. */
  const scheduleClose = useCallback(() => {
    suppressed.current = null            // the pointer has left; Escape's hold is spent
    cancelClose()
    closeTimer.current = window.setTimeout(() => {
      closeTimer.current = null
      setHoverId(null)
    }, CLOSE_MS)
  }, [cancelClose])

  useEffect(() => cancelClose, [cancelClose])

  useEffect(() => {
    if (openId === null) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') dismiss() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [openId, dismiss])

  /* Capture phase, so a pinned card still closes on a click that something else
     stops propagation on. The highlights themselves are excluded because their
     own click re-pins, and the card because its controls are the point of it. */
  useEffect(() => {
    if (pinnedId === null) return
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node | null
      if (!target) return
      if (cardRef.current?.contains(target)) return
      for (const el of anchorEls.current.values()) if (el.contains(target)) return
      dismiss()
    }
    document.addEventListener('pointerdown', onDown, true)
    return () => document.removeEventListener('pointerdown', onDown, true)
  }, [pinnedId, dismiss])

  useEffect(() => {
    const bump = () => setRemeasure((n) => n + 1)
    window.addEventListener('resize', bump)
    return () => window.removeEventListener('resize', bump)
  }, [])

  /* The card's own size decides the clamp, so it is mounted first and placed in a
     layout effect — before paint, so there is no frame at the wrong spot. */
  useLayoutEffect(() => {
    if (openId === null) { setPos(null); return }
    const el = anchorEls.current.get(openId)
    const stage = stageRef.current
    const card = cardRef.current
    const bounds = boundsRef.current
    if (!el || !stage || !card || !bounds) { setPos(null); return }
    const a = el.getBoundingClientRect()
    const st = stage.getBoundingClientRect()
    const c = card.getBoundingClientRect()
    const b = bounds.getBoundingClientRect()
    const clamp = (v: number, lo: number, hi: number) => (hi < lo ? lo : Math.min(Math.max(v, lo), hi))
    setPos({
      left: clamp(a.right - st.left + CARD_DX, b.left - st.left, b.right - st.left - c.width),
      top: clamp(a.bottom - st.top + RULE + ANCHOR_GAP, b.top - st.top, b.bottom - st.top - c.height),
    })
  }, [openId, remeasure, page, text, kind])

  /* An inline error, a busy label or an open edit form changes the card's height
     while it is on screen. */
  useEffect(() => {
    const card = cardRef.current
    if (openId === null || card === null) return
    const ro = new ResizeObserver(() => setRemeasure((n) => n + 1))
    ro.observe(card)
    return () => ro.disconnect()
  }, [openId])

  /* Only decides how a highlight is PAINTED. A settled one is drawn faint, but
     it stays a control: making it inert meant that resolving a conflict left a
     grey smudge on the page that could not be clicked, read or undone, which
     looks like the app breaking rather than like the work being done. */
  const isOpen = useCallback(
    (findingId: number) => open.some((h) => h.finding_id === findingId), [open])

  const handlers = useCallback((findingId: number): HighlightHandlers => ({
    onClick: () => pinCard(findingId),
    onMouseEnter: () => openCard(findingId),
    onMouseLeave: scheduleClose,
    onFocus: () => openCard(findingId),
    onBlur: scheduleClose,
    'aria-expanded': openId === findingId,
  }), [openId, pinCard, openCard, scheduleClose])

  /** The pinned highlight keeps the deepened tint the pointer gave it, so a card
   *  sitting there with the pointer long gone still shows what it is about. */
  const pinClass = (findingId: number) => (pinnedId === findingId ? s.pinned : '')

  /* Any open box carries page_size, not just one on the current page. */
  const pageSize = useMemo(() => open.filter(isBox)[0]?.page_size ?? null, [open])

  /* A finding with neither a box, a span nor a placeable quote (ticket 6) has
     nothing to hover, so its card drops into the flow rather than becoming
     unreachable. Read off the highlight payload rather than the refs, which land
     a commit late. */
  /* Quotes are deliberately NOT counted. They are no longer rendered, so a
     finding that only has a quote has no element to hang a card off — and
     counting it here would leave the card neither anchored nor dropped into
     the flow, which is to say invisible. Without it, that finding falls back
     to `anchorFlow` and stays reachable. */
  const canAnchor = highlights.filter(isBox).length + spans.length > 0

  /* Chrome's built-in PDF viewer insets the page by about four pixels on every
     side and anchors it to the TOP of whatever box it is given. A frame cut to
     the PDF's own aspect ratio therefore has nowhere to put the height those
     insets cost, and all of it collects underneath the page: measured on the
     addendum, four pixels of black down each side and nine along the bottom.
     Sizing the frame to the padded page instead — the page's ratio applied to
     the width LESS the two insets, plus the insets back — leaves the same four
     pixels on all four sides.
     The frame ends up ~3px shorter than the true ratio, which the overlay sits
     on top of, so a box drifts by 0.3% of its distance down the page: under a
     pixel for anything in the top half, where every flagged line on these
     documents is. */
  const PDF_VIEWER_INSET = 4
  const isPaddedPdf = kind === 'pdf' && pageSize !== null
  const pageStyle = useMemo(() => {
    if (!pageSize) return undefined
    if (kind !== 'pdf') return { aspectRatio: `${pageSize[0]} / ${pageSize[1]}` }
    const pad = 2 * PDF_VIEWER_INSET
    return {
      height: 0,
      paddingBottom: `calc((100% - ${pad}px) * ${pageSize[1] / pageSize[0]} + ${pad}px)`,
    }
  }, [kind, pageSize])

  return (
    <>
      <div className={s.pane}>
        <div className={s.content} ref={boundsRef}>
          {header && (
            <>
              <p className={`${s.metaLine} ${header.line1Overline ? 't-overline' : 't-caption'}`}>
                {header.line1}
              </p>
              {header.line2 && <p className={`${s.metaSub} t-caption`}>{header.line2}</p>}
              {header.subject && <p className={`${s.subject} t-body-md-b`}>{header.subject}</p>}
              <div className={s.headRule} aria-hidden />
            </>
          )}

          <div className={s.stage} ref={stageRef}>
            {kind === 'text' && (
              <TextDocument text={text} spans={spans} isOpen={isOpen}
                            handlers={handlers} pinClass={pinClass} register={register} />
            )}

            {(kind === 'pdf' || kind === 'image') && docId !== null && (
              <div className={`${s.page} ${isPaddedPdf ? s.pagePdf : ''}`} style={pageStyle}>
                {kind === 'image'
                  ? <img className={`${s.pageMedia} ${pageSize ? '' : s.mediaAuto}`}
                         src={urls.documentFile(docId)} alt="Source document" />
                  : <iframe className={`${s.pageMedia} ${pageSize ? '' : s.mediaTall}`} title="Source document"
                            src={`${urls.documentFile(docId)}#page=${page}&toolbar=0&navpanes=0&scrollbar=0&view=Fit`} />}
                <div className={s.overlay}>
                  {boxes.map((h) => {
                    const [x1, y1, x2, y2] = h.rect
                    const [w, ht] = h.page_size
                    const tone = HIGHLIGHT_TONE[h.severity]
                    const live = isOpen(h.finding_id)
                    return (
                      <button key={`${h.finding_id}-${x1}-${y1}`} type="button"
                              ref={(el) => register(h.finding_id, el)}
                              className={`${s.box} ${s[`box_${tone}`]} ${live ? '' : s.boxCleared} ${pinClass(h.finding_id)}`}
                              aria-label={`Finding ${h.finding_id}, ${h.severity}`}
                              {...handlers(h.finding_id)}
                              style={{
                                left: `calc(${(x1 / w) * 100}% - ${PAD_X}px)`,
                                top: `calc(${(y1 / ht) * 100}% - ${PAD_Y}px)`,
                                width: `calc(${((x2 - x1) / w) * 100}% + ${PAD_X * 2}px)`,
                                height: `calc(${((y2 - y1) / ht) * 100}% + ${PAD_Y * 2}px)`,
                              }} />
                    )
                  })}
                </div>
              </div>
            )}

            {kind === 'unknown' && (
              <p className={`${s.noPage} t-body-md`}>
                This file type carries no highlights.
              </p>
            )}

            {anchored && canAnchor && openId !== null && (
              <div ref={cardRef} className={s.anchor}
                   style={pos ? { left: pos.left, top: pos.top } : { visibility: 'hidden' }}
                   onMouseEnter={cancelClose} onMouseLeave={scheduleClose}
                   /* Focus reaching a control inside the card pins it: the
                      keyboard route in has to be as durable as the click. */
                   onFocus={() => { if (openId !== null) pinCard(openId) }}
                   onBlur={scheduleClose}>
                {typeof anchored === 'function' ? anchored(dismiss) : anchored}
              </div>
            )}
          </div>

          {anchored && !canAnchor && (
            <div className={s.anchorFlow}>
              {typeof anchored === 'function' ? anchored(dismiss) : anchored}
            </div>
          )}

          {/* No "quotes Bumpin could not place" list. A finding that cannot
              be put on the page is not evidence of anything on screen, and a
              column of orphaned quotes under the document reads as the parser
              apologising. Findings still exist on the ticket; only the list of
              unplaceable ones is gone. */}
        </div>
      </div>

      {/* 121:11 */}
      {/* 121:11. One thumb per FILE when the ticket carries several — an
          artist who sends a page plus an addendum has a conflict on each, and
          the strip is the only way to reach the second. With a single file it
          steps through that file's pages, as drawn. */}
      {(() => {
        const files = documents.length > 1 && onDocument ? documents : null
        const count = files ? files.length : pageCount
        const at = files ? Math.max(0, files.findIndex((f) => f.id === docId)) + 1 : page
        const go = (n: number) => {
          if (files) onDocument!(files[n - 1].id)
          else onPage(n)
        }
        const noun = files ? 'File' : 'Page'
        return (
          <div className={s.pager}>
            <button type="button" className={s.step} aria-label={`Previous ${noun.toLowerCase()}`}
                    disabled={at <= 1} onClick={() => go(at - 1)}>
              <svg className={s.pageNavIcon} width="6" height="14" viewBox="0 0 6 14" fill="none"
                   stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden>
                <path d="M 6 0 L 0 7 L 6 14" />
              </svg>
            </button>
            <div className={s.thumbs}>
              {Array.from({ length: count }, (_, i) => i + 1).map((n) => (
                <button key={n} type="button" className={`${s.thumb} ${n === at ? s.thumbOn : ''}`}
                        aria-label={files ? files[n - 1].filename : `Page ${n}`}
                        title={files ? files[n - 1].filename : undefined}
                        aria-current={n === at} onClick={() => go(n)}>
                  {/* 121:17..121:21 — bars 22/36/30/36/30 wide at y 12/23/34/45/56. */}
                  {[22, 36, 30, 36, 30].map((w, i) => (
                    <span key={i} className={s.bar} style={{ left: 10, top: 12 + i * 11, width: w }} />
                  ))}
                </button>
              ))}
            </div>
            <button type="button" className={s.step} aria-label={`Next ${noun.toLowerCase()}`}
                    disabled={at >= count} onClick={() => go(at + 1)}>
              <svg className={s.pageNavIcon} width="6" height="14" viewBox="0 0 6 14" fill="none"
                   stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden>
                <path d="M 0 0 L 6 7 L 0 14" />
              </svg>
            </button>
            <span className={`${s.pageCount} t-caption`}>{noun} {at} of {count}</span>
          </div>
        )
      })()}
    </>
  )
}

/** A text highlight is a span, not a button, so that the tint can break across
 *  lines; Enter and Space have to be wired by hand to keep it operable. */
const activate = (run: () => void) => (e: React.KeyboardEvent) => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); run() }
}

/** The `text` shape: `start` and `end` index into the document text, so the body
 *  is one pre-wrap block cut at those offsets. Overlapping spans are dropped
 *  rather than nested, so the offsets always stay in step with the string. */
function TextDocument({ text, spans, isOpen, handlers, pinClass, register }: {
  text: string | null
  spans: TextHighlight[]
  isOpen: (findingId: number) => boolean
  handlers: (findingId: number) => HighlightHandlers
  pinClass: (findingId: number) => string
  register: Register
}) {
  if (text === null) return <p className={`${s.noPage} t-body-md`}>Loading the document…</p>

  const sorted = [...spans]
    .filter((h) => h.start >= 0 && h.end > h.start && h.start < text.length)
    .sort((a, b) => a.start - b.start)

  const parts: ReactNode[] = []
  let cursor = 0
  for (const h of sorted) {
    if (h.start < cursor) continue              // overlapping — keep the earlier one
    const end = Math.min(h.end, text.length)
    if (h.start > cursor) parts.push(text.slice(cursor, h.start))
    const live = isOpen(h.finding_id)
    parts.push(
      <span key={`${h.finding_id}-${h.start}`}
            ref={(el) => register(h.finding_id, el)}
            className={`${s.mark} ${s[`mark_${HIGHLIGHT_TONE[h.severity]}`]} ${live ? '' : s.boxCleared} ${pinClass(h.finding_id)}`}
            tabIndex={0} role="button"
            aria-label={`Finding ${h.finding_id}, ${h.severity}`}
            onKeyDown={activate(() => handlers(h.finding_id).onClick())}
            {...handlers(h.finding_id)}>
        {text.slice(h.start, end)}
      </span>,
    )
    cursor = end
  }
  if (cursor < text.length) parts.push(text.slice(cursor))

  return <p className={s.textBody}>{parts}</p>
}

/** Pick the renderer from the highlight shapes, falling back to the filename. */
export function docKindOf(highlights: Highlight[], filename: string | undefined): DocKind {
  const first = highlights.find((h) => h.status === 'open') ?? highlights[0]
  if (first) return first.type
  const ext = (filename ?? '').toLowerCase().split('.').pop() ?? ''
  if (ext === 'pdf') return 'pdf'
  if (['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ext)) return 'image'
  if (['txt', 'eml', 'md', ''].includes(ext)) return 'text'
  return 'unknown'
}

/** `GET /documents/{id}/file` serves the extracted text for pasted documents. */
export function useDocumentText(docId: number | null, kind: DocKind) {
  const [text, setText] = useState<string | null>(null)
  useEffect(() => {
    if (docId === null || kind !== 'text') { setText(null); return }
    let alive = true
    setText(null)
    fetch(urls.documentFile(docId))
      .then((r) => r.text())
      .then((t) => { if (alive) setText(t) })
      .catch(() => { if (alive) setText('') })
    return () => { alive = false }
  }, [docId, kind])
  return text
}
