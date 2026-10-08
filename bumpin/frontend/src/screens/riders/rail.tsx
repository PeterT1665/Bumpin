/* The reading rail: a white panel, a donut with a two-row legend, and a
   label/value table. Transcribed from Figma 122:2, 122:6 and 122:19. */

import type { ReactNode } from 'react'
import { donutArcs } from './riders'
import s from './rail.module.css'

export function Panel({ reading = false, children }: { reading?: boolean; children: ReactNode }) {
  return <section className={`${s.panel} ${reading ? s.panelReading : ''}`}>{children}</section>
}

/** 122:2 — title is Funnel Display Medium 18/24 (129:2), paragraphs 16/24. */
export function ReadingPanel({ title, paragraphs }: { title: string; paragraphs: string[] }) {
  return (
    <Panel reading>
      <h2 className={`${s.panelTitleLg} t-heading-sm`}>{title}</h2>
      <div className={s.readingBody}>
        {paragraphs.map((p, i) => (
          <p key={i} className={`${s.readingP} t-body-md`}>{p}</p>
        ))}
      </div>
    </Panel>
  )
}

/* The ring on 129:8: a 96x96 ellipse with innerRadius 0.62, so the stroke sits
   at r = (48 + 48*0.62)/2 = 38.88 and is 48 - 48*0.62 = 18.24 wide. */
const R = 38.88
const W = 18.24
const C = 48

const pointAt = (deg: number) => {
  const r = (deg * Math.PI) / 180
  return [C + R * Math.cos(r), C + R * Math.sin(r)]
}

function arcPath(from: number, to: number) {
  const [x1, y1] = pointAt(from)
  const [x2, y2] = pointAt(to)
  const large = to - from > 180 ? 1 : 0
  return `M ${x1} ${y1} A ${R} ${R} 0 ${large} 1 ${x2} ${y2}`
}

export type DonutSlice = { label: string; value: number; tone: 'pink' | 'green' }

/** 122:6 — "Requests / 14 items" on the rider ticket, "Steps / 4 steps" on the
 *  help ticket (230:140). The centre number is the total. */
export function DonutPanel({ title, unit, slices }: {
  title: string
  unit: string
  slices: DonutSlice[]
}) {
  const total = slices.reduce((a, b) => a + b.value, 0)
  const arcs = donutArcs(slices.map((x) => x.value))
  const live = slices.filter((x) => x.value > 0)

  return (
    <Panel>
      <div className={s.donutHead}>
        <h2 className={`${s.panelTitleSm} t-label-md`}>{title}</h2>
        <span className={`${s.donutCount} t-label-sm`}>{total} {unit}</span>
      </div>
      <div className={s.donutRow}>
        <div className={s.donut}>
          <svg width="96" height="96" viewBox="0 0 96 96" aria-hidden>
            {arcs.map((a, i) => {
              const tone = live[i]?.tone ?? 'pink'
              const stroke = tone === 'green' ? 'var(--accent-green)' : 'var(--accent-pink)'
              // A single full-circle segment cannot be drawn as one arc.
              return a.to - a.from >= 359.9 ? (
                <circle key={i} cx={C} cy={C} r={R} fill="none" stroke={stroke} strokeWidth={W} />
              ) : (
                <path key={i} d={arcPath(a.from, a.to)} fill="none" stroke={stroke} strokeWidth={W} />
              )
            })}
          </svg>
          <div className={`${s.donutValue} t-heading-lg`}>{total}</div>
        </div>
        <div className={s.legend}>
          {slices.map((x) => (
            <div key={x.label} className={s.legendRow}>
              <span className={`${s.legendDot} ${s[`dot_${x.tone}`]}`} aria-hidden />
              <span className={`${s.legendLabel} t-body-sm`}>{x.label}</span>
              <span className={`${s.legendValue} t-label-md`}>{x.value}</span>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  )
}

export type DetailRow = { label: string; value: string }

/** 122:19 — rows whose value the backend cannot fill are left out by the
 *  caller rather than shown blank. */
export function DetailsPanel({ rows }: { rows: DetailRow[] }) {
  return (
    <Panel>
      <h2 className={`${s.panelTitleSm} t-label-md`}>Details</h2>
      <div className={s.details}>
        {rows.map((r) => (
          <div key={r.label} className={s.detailRow}>
            <span className={`${s.detailLabel} t-caption`}>{r.label}</span>
            <span className={`${s.detailValue} t-label-sm`}>{r.value}</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}
