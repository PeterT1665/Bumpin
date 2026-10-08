import { Card } from '@/components/primitives'
import type { Hospitality, IntakeDay, Readiness } from '@/api/types'
import s from './overview.module.css'

/* The three cards on the top row of "Bumpin — Dashboard" (13:2).
 *
 * All three are 400px tall with absolutely placed children in Figma, so each
 * `left` / `top` below is the literal Figma coordinate of that node. Node ids
 * are quoted so every number can be checked against the file.
 *
 * `GET /overview` now carries `intake`, `hospitality` and `readiness`, so all
 * three charts draw real data. Each field is still optional on the response
 * type, and each card falls back to its specimen from "Screen — Overview ·
 * empty" (231:385) when its field is missing or genuinely empty — a festival
 * with no mail yet has to read as "nothing has arrived", not as a broken card. */

const EMPTY_HERO = '—' // em dash, as in 231:517 / 231:555 / 231:670
const NO_DATA = 'No data yet'

/* ------------------------------------------------------------------ Intake */
/* 26:2 populated / 231:515 empty. Seven bottom-anchored stacks of
   clash / flagged / clean, plus the three-swatch legend at y=364 that only the
   populated frame carries. */

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/* Top of the stack down, matching the paint order of 143:7 / 143:6 / 143:5.
   The fills are sampled off 26:2, not guessed: clash is --accent-pink
   (#eba2d5), flagged --accent-yellow (#f0d977), clean --accent-green
   (#9eab6c) — the same three the legend swatches 143:33/35/37 use. */
const BUCKETS = [
  { key: 'clash', label: 'Clash', color: 'var(--accent-pink)' },
  { key: 'flagged', label: 'Flagged', color: 'var(--accent-yellow)' },
  { key: 'clean', label: 'Clean', color: 'var(--accent-green)' },
] as const

/* The track box is 231:519's 44x160 at y=160; 26:2 lets its tallest day run
   past that, but staying inside the transcribed box is what keeps the three
   cards the same height whatever the busiest day turns out to be.
   `seam` is the 2px measured between 143:7/143:6 and 143:6/143:5. `min` is the
   6px floor 143:27 and 143:31 both sit on, which is what stops a day that got
   one clash from rendering as nothing. `foot` is the 12px bottom radius on the
   last segment of a stack; every other corner is 3px. */
const TRACK = { height: 160, seam: 2, min: 6, radius: 3, foot: 12 }

type Segment = { key: string; color: string; height: number; foot: boolean }

/** One day's segments, top-first, scaled against the busiest day's total so
 *  that day fills the track. Buckets at zero are dropped rather than drawn at
 *  the 6px floor — a floor is for "one arrived", not for "none did". */
function stackOf(day: IntakeDay, busiest: number): Segment[] {
  const live = BUCKETS.map((b) => ({ ...b, value: day[b.key] })).filter((b) => b.value > 0)
  if (live.length === 0) return []

  /* A three-segment stack spends two seams on gaps, so that is the room the
     busiest day has to fill. Days with fewer segments land fractionally short
     of the track top, which is the honest way round: the scale is one number
     for the whole chart rather than one per column. */
  const room = TRACK.height - (BUCKETS.length - 1) * TRACK.seam
  const perEmail = room / busiest

  const segs = live.map((b) => ({
    key: b.key,
    color: b.color,
    height: Math.max(TRACK.min, b.value * perEmail),
    foot: false,
  }))

  /* The floor can push a stack past the track when the busiest day is itself
     mostly one bucket (say 98 clean, 1 flagged, 1 clash). The overflow comes
     off the tallest segment, which is the only one with height to spare. */
  const used = segs.reduce((a, g) => a + g.height, 0) + (segs.length - 1) * TRACK.seam
  if (used > TRACK.height) {
    const tallest = segs.reduce((a, b) => (b.height > a.height ? b : a))
    tallest.height = Math.max(TRACK.min, tallest.height - (used - TRACK.height))
  }

  segs[segs.length - 1].foot = true
  return segs
}

export function IntakeCard({ intake }: { intake?: IntakeDay[] }) {
  const days = intake?.length ? intake : null
  const tally = BUCKETS.map((b) => ({
    ...b,
    value: days ? days.reduce((a, d) => a + d[b.key], 0) : 0,
  }))
  const total = tally.reduce((a, b) => a + b.value, 0)
  /* No mail at all is the empty specimen, not seven empty tracks under a 0. */
  const busiest = days ? Math.max(...days.map((d) => d.clean + d.flagged + d.clash)) : 0
  const populated = days !== null && total > 0

  return (
    <Card className={s.statCard}>
      <div className={s.plane}>
        <h2 className={`${s.absLeft} ${s.cardTitle} t-heading-sm`} style={{ left: 28, top: 28 }}>
          Intake
        </h2>
        <p className={`${s.absLeft} ${s.hero} t-display-md`} style={{ left: 28, top: 52 }}>
          {populated ? total.toLocaleString('en-AU') : EMPTY_HERO}
        </p>
        <p className={`${s.absLeft} ${s.heroCap} t-body-sm`} style={{ left: 28, top: 102 }}>
          {populated ? 'emails parsed this week' : NO_DATA}
        </p>

        {/* 231:519..231:543 — 44x160 outlined tracks, 1px ink-line at 70%. A
            day with no mail keeps its outlined track so the week still reads as
            seven slots; a day with mail replaces it with its stack. */}
        <div className={`${s.absStretch} ${s.intakeTracks}`} aria-hidden>
          {DAYS.map((label, i) => {
            const segs = populated && days[i] ? stackOf(days[i], busiest) : []
            if (segs.length === 0) return <div key={label} className={s.track} />
            return (
              <div key={label} className={s.stack}>
                {segs.map((g) => (
                  <span
                    key={g.key}
                    className={`${s.seg} ${g.foot ? s.segFoot : ''}`}
                    style={{ height: g.height, background: g.color }}
                  />
                ))}
              </div>
            )
          })}
        </div>

        <div className={`${s.absStretch} ${s.intakeDays}`}>
          {DAYS.map((d) => <span key={d} className={`${s.day} t-label-sm`}>{d}</span>)}
        </div>

        {/* 143:33..143:38 — swatch at x=28/169/278, label+count as one run of
            ink-700 text. Only the populated frame has this row. */}
        {populated && (
          <div className={`${s.absLeft} ${s.intakeLegend}`} style={{ left: 28, top: 364 }}>
            {tally.map((b) => (
              <div key={b.key} className={`${s.intakeLegendItem} t-label-sm`}>
                <span className={s.intakeSwatch} style={{ background: b.color }} aria-hidden />
                <span>{b.label}</span>
                <span className={s.intakeLegendValue}>{b.value.toLocaleString('en-AU')}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}

/* ------------------------------------------------- Hospitality spend 157:2 */
/* 157:2 populated / 231:553 empty. Both specimens carry no stroke and no drop
   shadow on this one card.

   157:2 wraps each category across as many 19-cell lines as its figure needs
   (Catering runs to 38 cells at $1,000 a square). Real spend is three orders
   of magnitude smaller than the design's placeholder and the four label tops
   are fixed, so this keeps the single transcribed run of 19 per category and
   moves the dollars-per-square instead — the unit note 157:101 already exists
   to say what a square is worth. */

const SPEND_ROWS = [
  /* Ramp steps sampled off 157:8 / 157:48 / 157:74 / 157:91 — darkest category
     first, which is also how the four --spend-* tokens are ordered. */
  { name: 'Catering', top: 136, color: 'var(--spend-4)' },
  { name: 'Drinks', top: 198.9474, color: 'var(--spend-3)' },
  { name: 'Dressing', top: 261.8947, color: 'var(--spend-2)' },
  { name: 'Other', top: 310.3684, color: 'var(--spend-1)' },
]
const CELLS = 19 // 231:687..231:705 — one full run per category

/* Squares have to be worth a round number or the note reads as noise, and the
   longest run has to stay inside its 19 cells. 157:101 says "$1,000"; this is
   the same ladder, picked from the data instead of fixed. */
const UNITS = [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000]

const money = (n: number) => `$${Math.round(n).toLocaleString('en-AU')}`

export function SpendCard({ hospitality }: { hospitality?: Hospitality }) {
  const rows = hospitality?.rows?.length ? hospitality.rows : null
  const byName = new Map(rows?.map((r) => [r.name, r]) ?? [])

  const unit = UNITS.find((u) => Math.max(0, ...(rows ?? []).map((r) => r.spend)) / u <= CELLS)
    ?? UNITS[UNITS.length - 1]

  /* Every row is a slice of the same priced thing now, so the whole chart is
     one blue ramp — there is no row measured in a different unit and so no
     grey. A row at zero keeps 231:687's outlined cells. */
  const total = hospitality?.spend_total ?? 0
  const cap = hospitality?.cap_total ?? 0
  const populated = rows !== null && total > 0

  return (
    <Card className={`${s.statCard} ${s.noChrome}`}>
      <div className={s.plane}>
        <h2 className={`${s.absLeft} ${s.cardTitle} t-heading-sm`} style={{ left: 24, top: 28 }}>
          Hospitality spend
        </h2>
        <p className={`${s.absLeft} ${s.hero} t-display-md`} style={{ left: 24, top: 52 }}>
          {populated ? money(total) : EMPTY_HERO}
        </p>
        <p className={`${s.absLeft} ${s.heroCap} t-body-sm`} style={{ left: 24, top: 102 }}>
          {!populated ? NO_DATA
            : cap > 0 ? `of ${money(cap)} cap · ${Math.round((total / cap) * 100)}% used`
            : 'no cap on file'}
        </p>

        {SPEND_ROWS.map((row) => {
          const data = byName.get(row.name)
          const spend = data?.spend ?? 0
          /* A row with any spend at all gets at least one square, so a small
             category reads as present rather than as nothing. */
          const filled = spend > 0 ? Math.min(CELLS, Math.max(1, Math.round(spend / unit))) : 0

          return (
            <div key={row.name}>
              <div className={`${s.spendStretch} ${s.spendHead}`} style={{ top: row.top }}>
                <span className={`${s.spendLabel} t-label-sm`}>{row.name}</span>
                {/* 157:7 / 157:47 / 157:73 / 157:90 — right-aligned to x=296. */}
                <span className={`${s.spendValue} t-label-sm`}>
                  {spend > 0 ? money(spend) : EMPTY_HERO}
                </span>
              </div>
              {/* cells always start 21px below the top of their label */}
              <div className={`${s.spendStretch} ${s.spendRow}`} style={{ top: row.top + 21 }} aria-hidden>
                {Array.from({ length: CELLS }, (_, i) => (
                  <span
                    key={i}
                    className={`${s.cell} ${i < filled ? s.cellFill : s.cellEmpty}`}
                    style={i < filled ? { background: row.color } : undefined}
                  />
                ))}
              </div>
            </div>
          )
        })}

        {/* 157:101 */}
        <div className={`${s.spendStretch} ${s.unitNote} t-label-sm`} style={{ top: 352.8421 }}>
          {populated
            ? `Each square = ${money(unit)}`
            : 'No priced hospitality lines yet'}
        </div>
      </div>
    </Card>
  )
}

/* ---------------------------------------------------- Show readiness 35:2 */
/* 35:2 populated / 231:653 empty. `readiness_pct` feeds the hero; the five-way
   `readiness` split feeds the arc, the legend values and the card caption. */

const ARC = { cx: 200, cy: 262, r: 140, count: 13, w: 29, h: 56, radius: 13 }

/** Thirteen 29x56 pills (r=13) on a 140px radius about (200, 262), 180/13
 *  degrees apart — measured off 148:2..148:14. */
function arcSegments() {
  const step = 180 / ARC.count
  return Array.from({ length: ARC.count }, (_, i) => {
    const deg = (i - (ARC.count - 1) / 2) * step
    const rad = (deg * Math.PI) / 180
    return {
      deg,
      cx: ARC.cx + ARC.r * Math.sin(rad),
      cy: ARC.cy - ARC.r * Math.cos(rad),
    }
  })
}

/* Legend order is the arc's order, left to right: 148:2..148:8 are green,
   148:9..148:11 blue, 148:12 pink, 148:13 yellow, 148:14 outlined. */
const LEGEND: { key: keyof Readiness; label: string; color?: string }[] = [
  { key: 'cleared_rider', label: 'Cleared · rider', color: 'var(--accent-green)' },
  { key: 'cleared_vendor', label: 'Cleared · vendor', color: 'var(--accent-blue)' },
  { key: 'in_progress', label: 'In progress', color: 'var(--accent-pink)' },
  { key: 'not_started', label: 'Not started', color: 'var(--accent-yellow)' },
  { key: 'not_received', label: 'Not received' }, // 145:36 is outlined, not filled
]

/** Thirteen pills never divide evenly across five buckets, so the rounding is
 *  made explicit: every bucket with a real count is guaranteed one pill — a
 *  bucket the legend reports as 15 must not read as nothing on the arc — and
 *  the remaining pills go by largest remainder on each bucket's share. The
 *  result always sums to exactly ARC.count. Returns null when there is nothing
 *  to split, which is the empty specimen's case. */
function allocatePills(counts: number[], pills: number): number[] | null {
  const total = counts.reduce((a, b) => a + b, 0)
  const live = counts.map((c, i) => [c, i] as const).filter(([c]) => c > 0)
  if (total === 0 || live.length > pills) return null

  const out = counts.map((c) => (c > 0 ? 1 : 0))
  let left = pills - live.length
  const share = live.map(([c, i]) => ({ i, want: (c / total) * left }))
  for (const p of share) {
    const whole = Math.floor(p.want)
    out[p.i] += whole
    left -= whole
  }
  share.sort((a, b) => (b.want % 1) - (a.want % 1))
  for (let k = 0; k < left; k++) out[share[k % share.length].i] += 1
  return out
}

export function ReadinessCard({
  readinessPct,
  readiness,
}: {
  readinessPct: number | null
  readiness?: Readiness
}) {
  const counts = readiness ? LEGEND.map((l) => readiness[l.key]) : null
  const total = counts?.reduce((a, b) => a + b, 0) ?? 0
  const pills = counts ? allocatePills(counts, ARC.count) : null

  /* Pill i's colour, in legend order. Buckets at zero contribute nothing, and
     'Not received' contributes outlined pills, so the tail of the arc is the
     only place `undefined` appears. */
  const paint = pills
    ? pills.flatMap((n, i) => Array.from({ length: n }, () => LEGEND[i].color))
    : null

  return (
    <Card className={s.statCard}>
      <div className={s.plane}>
        <h2 className={`${s.absLeft} ${s.cardTitle} t-heading-sm`} style={{ left: 28, top: 28 }}>
          Show readiness
        </h2>
        {/* 145:3 — the denominator the five buckets partition. */}
        <p className={`${s.absLeft} ${s.heroCap} t-body-sm`} style={{ left: 28, top: 56 }}>
          {counts ? `${total.toLocaleString('en-AU')} rider & vendor items` : NO_DATA}
        </p>

        {/* 148:2..148:14 populated, 231:656 empty — every segment outlined and
            the whole frame at 50%. The 2px stroke is INSIDE in Figma, so the
            path is inset 1px to match. */}
        <svg className={`${s.arc} ${paint ? '' : s.arcEmpty}`} viewBox="0 0 400 400" aria-hidden>
          {arcSegments().map((seg, i) => {
            const fill = paint?.[i]
            return (
              <rect
                key={i}
                x={seg.cx - ARC.w / 2 + 1}
                y={seg.cy - ARC.h / 2 + 1}
                width={ARC.w - 2}
                height={ARC.h - 2}
                rx={ARC.radius - 1}
                fill={fill ?? 'none'}
                stroke={fill ? 'none' : 'var(--ink-300)'}
                strokeWidth={2}
                transform={`rotate(${seg.deg} ${seg.cx} ${seg.cy})`}
              />
            )
          })}
        </svg>

        <p className={`${s.readyHero} t-display-lg`}>
          {readinessPct === null ? EMPTY_HERO : `${readinessPct}%`}
        </p>
        <p className={`${s.readyHeroCap} t-body-md`}>
          {readinessPct === null ? NO_DATA : 'Overall readiness'}
        </p>

        <div className={s.legend}>
          {LEGEND.map((item, i) => (
            <div key={item.label} className={s.legendItem}>
              <span
                className={`${s.swatch} ${item.color ? '' : s.swatchOutline}`}
                style={item.color ? { background: item.color } : undefined}
                aria-hidden
              />
              <div className={`${s.legendLabel} t-label-sm`}>{item.label}</div>
              <div className={`${s.legendValue} t-label-md`}>
                {counts ? counts[i].toLocaleString('en-AU') : EMPTY_HERO}
              </div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  )
}
