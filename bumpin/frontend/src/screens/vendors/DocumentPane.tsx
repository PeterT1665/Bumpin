import {
  useCallback, useEffect, useLayoutEffect, useRef, useState,
} from 'react'
import { api, urls } from '@/api/client'
import type { Finding, Highlight } from '@/api/types'
import type { VendorDocument } from './vendorModel'
import { kindLabel, longDate } from './vendorModel'
import s from './vendors.module.css'

/* The source-document pane — Figma 176:33, with the in-place highlights of
   180:4…180:22.
 *
 * `GET /documents/{id}/highlights` returns three shapes and this handles all
 * three (docs/CONTRACT.md §10, §13):
 *   pdf    — `rect` in PDF points with `page_size`; drawn at rect / page_size.
 *   image  — `rect` in image pixels with `page_size`; same proportional math.
 *   text   — `start`/`end` character offsets into `GET /documents/{id}/file`;
 *            that span is underlined in place.
 * Origin is top-left in every case.
 *
 * Only `severity: "conflict"` reads as a conflict, and it reads as
 * `accent/pink` used as a soft fill with dark text (180:234 #f7deee fill +
 * 180:233 #eba2d5 underline) — never as a text colour. Entries whose `status`
 * is not `open` are greyed.
 *
 * NOTHING ON THIS SCREEN SITS OUTSIDE A HIGHLIGHT. Every card is revealed from
 * the thing it talks about, so the area under the source is empty until the
 * operator points at something. Three shapes can be that anchor: a box over a
 * page, a `<mark>` in a text document, and the quote (or, with no quote, the
 * message) a finding with no box falls back to. All three carry the same
 * hover/focus/click wiring, so every finding handed to this pane has exactly
 * one anchor and no card can become unreachable.
 *
 * Hover reveals; a click, or focus landing inside the card, PINS. The cards hold
 * Approve, Deny, Resolve and Ignore, and Resolve opens a modal — a surface
 * that evaporates on pointer-out cannot be operated, so a pinned card stays up
 * until Escape or a click outside it.
 *
 * The rider ticket pane (`screens/riders/DocumentPane.tsx`) carries the same
 * mechanism; the slices were built in parallel and it is duplicated here rather
 * than imported across the boundary — see the report's promotion candidates. */

type Tone = 'conflict' | 'warning' | 'info' | 'muted'

type BoxHighlight = Extract<Highlight, { type: 'pdf' | 'image' }>
type TextHighlight = Extract<Highlight, { type: 'text' }>

const isBox = (h: Highlight): h is BoxHighlight => h.type === 'pdf' || h.type === 'image'
const isText = (h: Highlight): h is TextHighlight => h.type === 'text'

const toneOf = (h: Highlight): Tone =>
  h.status !== 'open' ? 'muted'
    : h.severity === 'conflict' ? 'conflict'
    : h.severity === 'warning' ? 'warning'
    : 'info'

const findingTone = (f: Finding): Tone =>
  f.status !== 'open' ? 'muted'
    : f.severity === 'conflict' ? 'conflict'
    : f.severity === 'warning' ? 'warning'
    : 'info'

/** The card's top-left hangs off the highlight's bottom-right: 4px clear of the
 *  right edge, and below the 2px underline plus an 8px gap. Neither spacing is
 *  in Figma — 176:65 is hand-placed under the page — so this is the pane's
 *  choice, matched to the rider pane so the two screens behave alike. */
const CARD_DX = 4
const RULE = 2
const ANCHOR_GAP = 8
/** The pointer has to cross RULE + ANCHOR_GAP of bare page to reach the card, so
 *  leaving either only *schedules* the close and entering the other cancels it. */
const CLOSE_MS = 180

/** Open/close wiring for one highlight, whichever shape it is. */
type AnchorHandlers = {
  onClick: () => void
  onMouseEnter: () => void
  onMouseLeave: () => void
  onFocus: () => void
  onBlur: () => void
  onKeyDown: (e: React.KeyboardEvent) => void
  'aria-expanded': boolean
}

type Register = (findingId: number, el: HTMLElement | null) => void

/** A card and the finding whose highlight reveals it. */
export type FindingCard = { findingId: number; node: React.ReactNode }

export function DocumentPane({ doc, findings, cards = [] }: {
  doc: VendorDocument | null
  findings: Finding[]
  /** Exactly one per open finding, revealed from that finding's own highlight.
   *  The pane used to take a second `decision` card hung off the ticket's worst
   *  finding as well, which gave that one highlight two cards saying the same
   *  sentence; the ticket verdict now rides in the footer of the finding's own
   *  card, so one anchor is one card. */
  cards?: FindingCard[]
}) {
  const [highlights, setHighlights] = useState<Highlight[] | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  /* ---- the revealed card ---- */

  const [openId, setOpenId] = useState<number | null>(null)
  /** Pointer-out closes a hovered card and must not close a pinned one.
   *
   *  A ref rather than state, because a click and the pointer leaving arrive in
   *  one gesture: a `mouseleave` handler built in the pre-click render would
   *  still be carrying `pinned: false` and would schedule a close the pin can no
   *  longer cancel. Nothing in the render reads it, so there is nothing to
   *  re-render for either. */
  const pinned = useRef(false)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  /** One entry per rendered anchor, so the card is placed off the real element
     instead of recomputing the page maths. */
  const anchorEls = useRef(new Map<number, HTMLElement>())
  const stageRef = useRef<HTMLDivElement | null>(null)
  const boundsRef = useRef<HTMLDivElement | null>(null)
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const cardRef = useRef<HTMLDivElement | null>(null)
  const closeTimer = useRef<number | null>(null)
  /** Set only while focus is being handed back to the anchor on close, so that
     handoff does not read as a fresh hover and reopen what was just dismissed. */
  const reclaiming = useRef(false)
  const [remeasure, setRemeasure] = useState(0)

  useEffect(() => {
    setHighlights(null)
    setText(null)
    setFailed(false)
    setOpenId(null)
    pinned.current = false
    if (!doc) return
    let live = true
    ;(async () => {
      try {
        const hs = await api.highlights(doc.id)
        if (!live) return
        setHighlights(hs)
        if (hs.some((h) => h.type === 'text')) {
          const res = await fetch(urls.documentFile(doc.id))
          const body = await res.text()
          if (live) setText(body)
        }
      } catch {
        if (live) setFailed(true)
      }
    })()
    return () => { live = false }
  }, [doc?.id])

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

  const close = useCallback(() => {
    cancelClose()
    /* Dismissing from inside the card would otherwise drop focus on the body and
       lose the keyboard's place in the document, so it goes back to the anchor. */
    const anchor = openId === null ? null : anchorEls.current.get(openId)
    if (anchor && cardRef.current?.contains(document.activeElement)) {
      reclaiming.current = true
      anchor.focus()
      reclaiming.current = false
    }
    setOpenId(null)
    pinned.current = false
  }, [cancelClose, openId])

  /** Hover and keyboard focus reveal. A pinned card owns the surface: a pointer
   *  crossing another highlight must not swap it out from under the buttons
   *  someone is reaching for. */
  const openCard = useCallback((findingId: number) => {
    cancelClose()
    if (pinned.current) return
    setOpenId(findingId)
  }, [cancelClose])

  /** A click, or focus landing in the card, holds it open. Re-pinning the card
   *  that is already pinned is a no-op rather than a toggle: these are the only
   *  controls on the screen and a second click must not throw them away. */
  const pinCard = useCallback((findingId: number) => {
    cancelClose()
    setOpenId(findingId)
    pinned.current = true
  }, [cancelClose])

  const scheduleClose = useCallback(() => {
    if (pinned.current) return
    cancelClose()
    closeTimer.current = window.setTimeout(() => {
      closeTimer.current = null
      /* Re-read: the pin can land inside the delay. */
      if (!pinned.current) setOpenId(null)
    }, CLOSE_MS)
  }, [cancelClose])

  useEffect(() => cancelClose, [cancelClose])

  /* Escape dismisses, and a click anywhere but the card or its own anchor does
     too. Both step aside while a modal is up: the Resolve modal is opened FROM
     the card, so its Escape and its scrim click belong to it, and the card has
     to still be there when it closes. */
  useEffect(() => {
    if (openId === null) return
    const modalUp = () => Boolean(document.querySelector('[role="dialog"]'))
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !modalUp()) close()
    }
    const onDown = (e: Event) => {
      const t = e.target as Node | null
      if (!t || modalUp()) return
      if (cardRef.current?.contains(t)) return
      if (anchorEls.current.get(openId)?.contains(t)) return
      close()
    }
    window.addEventListener('keydown', onKey)
    /* Capture, so a press on some other control dismisses before that control
       acts on it rather than a frame later. */
    document.addEventListener('pointerdown', onDown, true)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onDown, true)
    }
  }, [openId, close])

  /* The page scrolls inside the pane, so a scroll moves the highlight out from
     under an open card. Both scrollers and the window re-place it. */
  useEffect(() => {
    if (openId === null) return
    const bump = () => setRemeasure((n) => n + 1)
    const vp = viewportRef.current
    const surface = boundsRef.current
    window.addEventListener('resize', bump)
    vp?.addEventListener('scroll', bump, { passive: true })
    surface?.addEventListener('scroll', bump, { passive: true })
    return () => {
      window.removeEventListener('resize', bump)
      vp?.removeEventListener('scroll', bump)
      surface?.removeEventListener('scroll', bump)
    }
  }, [openId])

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
    const loTop = b.top - st.top
    const hiTop = b.bottom - st.top - c.height
    const below = a.bottom - st.top + RULE + ANCHOR_GAP
    const above = a.top - st.top - ANCHOR_GAP - c.height
    /* Under the highlight by preference. A quote near the foot of the surface
       leaves less room than a long card needs, and clamping it back into
       the surface would slide it over the very line it describes — so it goes
       above instead, and only falls back to the clamp when neither side fits. */
    setPos({
      left: clamp(a.right - st.left + CARD_DX, b.left - st.left, b.right - st.left - c.width),
      top: below <= hiTop ? below : above >= loTop ? above : clamp(below, loTop, hiTop),
    })
  }, [openId, remeasure, highlights, text])

  /* An inline error, a reason field, or a row settling into its decided state
     changes the card's height while it is open. */
  useEffect(() => {
    const card = cardRef.current
    if (openId === null || card === null) return
    const ro = new ResizeObserver(() => setRemeasure((n) => n + 1))
    ro.observe(card)
    return () => ro.disconnect()
  }, [openId])

  const handlers = useCallback((findingId: number): AnchorHandlers => ({
    onClick: () => pinCard(findingId),
    onMouseEnter: () => openCard(findingId),
    onMouseLeave: scheduleClose,
    onFocus: () => { if (!reclaiming.current) openCard(findingId) },
    onBlur: scheduleClose,
    onKeyDown: (e) => {
      /* A quote or a text highlight is a `<mark>`/`<span>` rather than a button,
         so that its tint can break across lines; Enter and Space have to be
         wired by hand. A box is a real button and fires its own click for both.
         Either way the keyboard ACTIVATES, which pins. */
      if (e.key === 'Enter' || e.key === ' ') {
        if (e.currentTarget.tagName !== 'BUTTON') { e.preventDefault(); pinCard(findingId) }
        return
      }
      /* Tabbing out of an open highlight lands in ITS card. Without this the next
         stop is the next highlight, which opens its own card and swaps the one
         the keyboard was heading for out from underneath it. */
      if (e.key === 'Tab' && !e.shiftKey && openId === findingId) {
        const first = cardRef.current?.querySelector<HTMLElement>('button:not([disabled])')
        if (first) { e.preventDefault(); cancelClose(); first.focus() }
      }
    },
    'aria-expanded': openId === findingId,
  }), [openId, openCard, pinCard, scheduleClose, cancelClose])

  /* ---- what is on screen ---- */

  const all = highlights ?? []
  const pageSized = all.find(isBox) ?? null
  const spans = text !== null ? placeSpans(text, all.filter(isText)) : []
  const pageNo = pageSized ? pageSized.page || 1 : 1
  const boxes = all.filter(isBox).filter((h) => (h.page || 1) === pageNo)

  /* Which highlights are really drawn is read off the payload, not off the refs:
     a ref lands a commit after its card would first have rendered, so deciding on
     refs paints a card for one frame before the page is ready to hold it.

     Anything NOT drawn falls back to its quote (or, with no quote, its message)
     under the source, and that fallback is an anchor too — the union is therefore
     every finding the pane was handed, which is what keeps "every card comes
     from a highlight" from meaning "some cards are unreachable". */
  const drawn = new Set<number>([
    ...boxes.map((h) => h.finding_id),
    ...spans.map((p) => p.h.finding_id),
  ])
  const quoted = findings.filter((f) => !drawn.has(f.id))
  const anchorable = new Set<number>([...drawn, ...quoted.map((f) => f.id)])

  const own = openId !== null && anchorable.has(openId)
    ? cards.find((c) => c.findingId === openId)?.node ?? null
    : null

  return (
    <div className={`${s.panel} ${s.panelDoc} ${s.docPanel}`}>
      <div className={s.docSurface} ref={boundsRef}>
        {/* 178:2 / 178:3 / 178:4 — the issuer and kind are two halves of one
            label, so they are joined by the same middot the meta line uses. */}
        {doc ? (
          <>
            <p className={`${s.docHead} t-overline`}>
              {(doc.issuer ?? 'SOURCE DOCUMENT').toUpperCase()} · {kindLabel(doc.kind).toUpperCase()}
            </p>
            <p className={`${s.docSub} t-caption`}>
              {doc.filename}
              {doc.expiry_date ? ` · valid until ${longDate(doc.expiry_date)}` : ' · no expiry parsed'}
            </p>
          </>
        ) : (
          /* Ticket 6 shape: a finding with no document behind it at all. */
          <>
            <p className={`${s.docHead} t-overline`}>NO DOCUMENT ON FILE</p>
            <p className={`${s.docSub} t-caption`}>
              Nothing has been received for this requirement, so there is no source to show.
            </p>
          </>
        )}
        <hr className={s.docDivider} />

        {failed && <p className={`${s.quote} t-body-sm`}>Could not read the highlights for this document.</p>}

        {/* The anchors and the card they open share one positioning context, and
            the card is a SIBLING of the page's scroller so the scroller cannot
            clip it. The quote list is inside the stage for the same reason: a
            quote is an anchor, so its card is placed against the same origin. */}
        <div className={s.stage} ref={stageRef}>
          {doc && (text !== null
            ? <TextDocument text={text} spans={spans} handlers={handlers} register={register} />
            : pageSized
              ? (
                <PageDocument
                  doc={doc}
                  first={pageSized}
                  boxes={boxes}
                  handlers={handlers}
                  register={register}
                  viewportRef={viewportRef}
                />
              )
              : highlights !== null && <PlainSource doc={doc} />)}

          {quoted.length > 0 && (
            <QuoteList findings={quoted} handlers={handlers} register={register} />
          )}

          {own && (
            <div
              key={openId}
              ref={cardRef}
              className={s.anchorCard}
              style={pos ? { left: pos.left, top: pos.top } : { visibility: 'hidden' }}
              onMouseEnter={cancelClose}
              onMouseLeave={scheduleClose}
              /* Focus reaching a control inside the card is a commitment to use
                 it, so it pins — the pointer is then free to leave. */
              onFocus={() => { if (openId !== null) pinCard(openId) }}
              onBlur={scheduleClose}
            >
              {own}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ pieces */

/** The spans `TextDocument` will actually draw: in bounds, in order, and with
 *  overlaps dropped rather than nested so the offsets stay in step with the
 *  string. Shared with the anchor bookkeeping, so a card only counts as drawn
 *  when its highlight really is on the page. */
function placeSpans(text: string, highlights: TextHighlight[]) {
  const out: { h: TextHighlight; start: number; end: number }[] = []
  let cursor = 0
  for (const h of [...highlights].sort((a, b) => a.start - b.start)) {
    if (h.start < 0) continue
    const start = Math.max(cursor, h.start)
    const end = Math.min(text.length, h.end)
    if (end <= start) continue
    out.push({ h, start, end })
    cursor = end
  }
  return out
}

/** `type: "text"` — underline the `start`/`end` span of the served file. */
function TextDocument({ text, spans, handlers, register }: {
  text: string
  spans: ReturnType<typeof placeSpans>
  handlers: (findingId: number) => AnchorHandlers
  register: Register
}) {
  const parts: React.ReactNode[] = []
  let cursor = 0
  spans.forEach(({ h, start, end }, i) => {
    if (start > cursor) parts.push(text.slice(cursor, start))
    parts.push(
      <mark
        key={`${h.finding_id}-${i}`}
        ref={(el) => register(h.finding_id, el)}
        className={`${s.mark} ${s[`mark_${toneOf(h)}`]}`}
        tabIndex={0}
        role="button"
        aria-label={`Finding ${h.finding_id}, ${h.severity}`}
        {...handlers(h.finding_id)}
      >
        {text.slice(start, end)}
      </mark>,
    )
    cursor = end
  })
  if (cursor < text.length) parts.push(text.slice(cursor))

  return <p className={`${s.docText} t-body-sm`}>{parts}</p>
}

/** `type: "pdf"` / `type: "image"` — a page-shaped box with the rects laid over
 *  it at `rect / page_size` of the rendered size.
 *
 *  The page keeps its paper aspect ratio and SCROLLS inside a capped viewport
 *  rather than being scaled: the boxes are positioned in percentages of the page
 *  box, so cropping the view leaves every one of them exactly over its line,
 *  where a transform would have to be applied to page and overlay together. */
function PageDocument({ doc, first, boxes, handlers, register, viewportRef }: {
  doc: VendorDocument
  first: BoxHighlight
  boxes: BoxHighlight[]
  handlers: (findingId: number) => AnchorHandlers
  register: Register
  viewportRef: React.MutableRefObject<HTMLDivElement | null>
}) {
  const [pw, ph] = first.page_size
  const page = first.page || 1
  const url = urls.documentFile(doc.id)

  return (
    <div className={s.pageViewport} ref={viewportRef}>
      <div className={s.page} style={{ aspectRatio: `${pw} / ${ph}` }}>
        {first.type === 'image'
          ? <img className={s.pageImg} src={url} alt={doc.filename} />
          : (
            <object
              className={s.pageMedia}
              type="application/pdf"
              data={`${url}#page=${page}&view=Fit&toolbar=0&navpanes=0&scrollbar=0`}
              aria-label={doc.filename}
            >
              <a href={url}>{doc.filename}</a>
            </object>
          )}
        {boxes.map((h, i) => {
          const [x0, y0, x1, y1] = h.rect
          return (
            <button
              key={`${h.finding_id}-${i}`}
              type="button"
              ref={(el) => register(h.finding_id, el)}
              className={`${s.box} ${s[`box_${toneOf(h)}`]}`}
              aria-label={`Finding ${h.finding_id}, ${h.severity}`}
              {...handlers(h.finding_id)}
              style={{
                left: `${(x0 / pw) * 100}%`,
                top: `${(y0 / ph) * 100}%`,
                width: `${((x1 - x0) / pw) * 100}%`,
                height: `${((y1 - y0) / ph) * 100}%`,
              }}
            >
              <span className={s.boxFill} aria-hidden />
            </button>
          )
        })}
      </div>
    </div>
  )
}

/** A document with nothing flagged on it. The parse ran and came back clean —
 *  that is the ordinary case now that only conflicts and warnings are stored —
 *  so the file is simply offered as-is. */
function PlainSource({ doc }: { doc: VendorDocument }) {
  return (
    <p className={`${s.docText} t-body-sm`}>
      Clean. Nothing on this document needed flagging.{' '}
      <a href={urls.documentFile(doc.id)} target="_blank" rel="noreferrer">
        Open {doc.filename}
      </a>
    </p>
  )
}

/** A finding with no box shows its quote as text, in the same tint — and when it
 *  has no quote either (ticket 6 shape: a missing document, so nothing was ever
 *  parsed) its message stands in.
 *
 *  Both are anchors, with the same wiring the boxes have: for a finding the open
 *  document cannot draw, this is the only place its card can be reached from. */
function QuoteList({ findings, handlers, register }: {
  findings: Finding[]
  handlers: (findingId: number) => AnchorHandlers
  register: Register
}) {
  return (
    <div className={s.quoteList}>
      {findings.map((f) => {
        const tone = findingTone(f)
        const label = `Finding ${f.id}, ${f.severity}`
        return (
          <p key={f.id} className={`${s.quote} t-body-sm`}>
            {f.quote
              ? (
                <mark
                  ref={(el) => register(f.id, el)}
                  className={`${s.mark} ${s[`mark_${tone}`]}`}
                  tabIndex={0}
                  role="button"
                  aria-label={label}
                  {...handlers(f.id)}
                >
                  {f.quote}
                </mark>
              )
              : (
                /* Bumpin's own sentence rather than a quotation off the page, so
                   it keeps the 2px tone rule and drops the fill. */
                <span
                  ref={(el) => register(f.id, el)}
                  className={`${s.quoteMark} ${s[`quoteRule_${tone}`]}`}
                  tabIndex={0}
                  role="button"
                  aria-label={label}
                  {...handlers(f.id)}
                >
                  {f.message}
                </span>
              )}
          </p>
        )
      })}
    </div>
  )
}
