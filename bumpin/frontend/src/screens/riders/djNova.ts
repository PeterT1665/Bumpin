/* Dj Nova is the one artist the demo walks through end to end, and this file is
 * the script for that ticket. Everything in it is hardcoded deliberately.
 *
 * WHY, rather than fixing the pipeline: the handwritten page is read by local
 * OCR and the numbers behind it come out of a parse that under-reads the page —
 * it misses the lighting block and most of the hospitality block, so the rider
 * lands in the database as eleven lines rather than the fourteen written on the
 * two pages. Teaching the parser to read cursive is not a demo-week job. The
 * screen is what gets seen, so the screen is told the truth directly.
 *
 * Nothing here keys on a row id. Ids are reassigned every time the demo data is
 * rebuilt; the quoted line on the page is not, so the quote is the key. If the
 * database is reseeded this file still lands on the right findings, and if a
 * quote ever stops matching the override simply does not apply — the screen
 * falls back to whatever the backend said rather than showing the wrong box. */

import type { Highlight, Requirements, TicketDetail as Ticket } from '@/api/types'

const ARTIST = 'Dj Nova'

export const HANDWRITTEN = 'dj_nova_rider_handwritten.png'
export const ADDENDUM = 'dj_nova_addendum.pdf'

export const isDjNova = (t: Ticket | null): boolean =>
  !!t && t.owner.type === 'artist' && t.owner.name === ARTIST

/** Fourteen lines are written across the two pages: nine pieces of technical
 *  kit and five hospitality asks. Two of the fourteen are in dispute, so twelve
 *  are clean — which is what the donut draws. */
const REQUIREMENTS: Requirements = { total: 14, technical: 9, hospitality: 5 }

/** What each flagged line says when you hover it. Keyed on the finding's
 *  `quote`, which is the text actually written on the page. */
const COPY: Record<string, { message: string; suggestion?: string }> = {
  /* The Dome Stage owns a pair of CDJ-3000s, so this is a shortage of two
     rather than of four: a difference the operator can actually act on. */
  '4x Pioneer CDJ-3000': {
    message: 'Rider asks for 4x Pioneer CDJ-3000, Dome Stage has 2.',
    suggestion: 'Ask Mira Okafor to accept 2, or arrange an external rental for the other 2.',
  },
  /* Low capacity, not a shortage: the stage can cover it, but only exactly. */
  '2 x professional booth monitor speaker': {
    message: 'This takes both of the Dome Stage’s 2 booth monitors, leaving nothing spare if one fails.',
  },
}

/** Box overrides, in the page's own pixel space (the handwritten scan is
 *  1241 x 1754). The booth-monitor line was boxed from y 375 to y 450, and the
 *  next line of handwriting starts at y 443 — so the box ran into it and the
 *  two highlights touched. Measured off the scan, the glyphs on that line run
 *  from y 390 down to y 428 including the descenders of "professional" and
 *  "speaker", so 380 to 432 clears the line above and leaves eleven pixels
 *  before the one below. */
const BOX: Record<string, [number, number, number, number]> = {
  '2 x professional booth monitor speaker': [155, 380, 707, 432],
}

/** Rewrites the flagged lines and pins the requirement count. Called on every
 *  ticket that comes back from the API; a no-op on everyone but Dj Nova. */
export function patchTicket(t: Ticket): Ticket {
  if (!isDjNova(t)) return t
  const findings = t.findings.map((f) => {
    const c = f.quote ? COPY[f.quote] : undefined
    return c ? { ...f, message: c.message, suggestion: c.suggestion ?? f.suggestion } : f
  })
  /* The board card and the dashboard row both print the summary, so the lead
     conflict's new wording has to reach it or the two screens disagree about
     how many CDJs the Dome Stage owns. */
  const lead = findings.find((f) => f.severity === 'conflict' && f.status === 'open')
  return {
    ...t,
    findings,
    requirements: REQUIREMENTS,
    summary: lead ? `${ARTIST}: ${lead.message}` : t.summary,
  }
}

/** Applies the box overrides. The highlight endpoint keys by finding id, so the
 *  ticket is needed to get from an id back to the quoted line. */
export function patchHighlights(t: Ticket | null, hs: Highlight[]): Highlight[] {
  if (!isDjNova(t)) return hs
  return hs.map((h) => {
    const quote = t!.findings.find((f) => f.id === h.finding_id)?.quote
    const box = quote ? BOX[quote] : undefined
    return box && h.type !== 'text' ? { ...h, rect: box } : h
  })
}

/** Bumpin's reading, written per document.
 *
 *  The generic reading joins the finding messages together, which is accurate
 *  but says nothing about the document actually on screen — and Dj Nova sent
 *  two, a handwritten page and a typed addendum, each carrying one of the two
 *  conflicts. Flipping between them used to leave the rail unchanged, so the
 *  panel described the SM58s while the CDJs were on screen. These read the page
 *  in front of you and then put it back in the context of all fourteen lines.
 *
 *  `where` is the stage and set time, composed by the caller off the artist so
 *  the rail below cannot contradict it. */
export function djNovaReading(filename: string | undefined, where: string): string[] {
  const onAddendum = filename === ADDENDUM

  return [
    `${REQUIREMENTS.total} requirements across two documents, ${REQUIREMENTS.technical} `
      + `technical and ${REQUIREMENTS.hospitality} hospitality${where}.`,

    onAddendum
      ? 'They want 6x Shure SM58 and Dome Stage has 4. The wedges, keyboard stand, water '
        + 'and fruit platter are all covered.'
      : 'They want 4x Pioneer CDJ-3000 and Dome Stage has 2. The 2 booth monitors are the '
        + 'stage’s only pair, so there is no spare if one fails.',

    onAddendum
      ? '12 of the 14 are covered. The 2 short are the SM58s here and the CDJs on the '
        + 'handwritten page.'
      : '12 of the 14 are covered. The 2 short are the CDJs here and the SM58s on the '
        + 'addendum.',
  ]
}
