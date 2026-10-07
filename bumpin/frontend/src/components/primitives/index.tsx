import type { ButtonHTMLAttributes, ReactNode } from 'react'
import type { Severity } from '@/api/types'
import s from './primitives.module.css'

/* The pieces that actually repeat across the twelve screens. Anything used on
   exactly one screen belongs in that screen's folder, not here. */

export function Card({ title, sub, actions, children, className = '' }: {
  title?: string
  sub?: string
  actions?: ReactNode
  children?: ReactNode
  className?: string
}) {
  return (
    <section className={`${s.card} ${className}`}>
      {(title || actions) && (
        <header className={s.cardHead}>
          <div>
            {title && <h2 className={`${s.cardTitle} t-heading-sm`}>{title}</h2>}
            {sub && <p className={`${s.cardSub} t-caption`}>{sub}</p>}
          </div>
          {actions && <div className={s.cardActions}>{actions}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

/** Conflict is pink, not red — there is no red anywhere in this system. */
export function StatusPill({ label, tone = 'neutral' }: {
  label: string
  tone?: 'ok' | 'progress' | 'warn' | 'neutral'
}) {
  return (
    <span className={`${s.pill} ${s[`pill_${tone}`]} t-label-sm`}>
      <span className={s.dot} aria-hidden />
      {label}
    </span>
  )
}

export function Chip({ children, tone = 'pink' }: {
  children: ReactNode
  tone?: 'pink' | 'green' | 'yellow' | 'blue' | 'quiet'
}) {
  return <span className={`${s.chip} ${s[`chip_${tone}`]} t-caption`}>{children}</span>
}

/** Red is never used; conflict reads as pink, warning as yellow, info as blue. */
export const severityTone = (sev: Severity) =>
  sev === 'conflict' ? 'pink' : sev === 'warning' ? 'yellow' : 'blue'

export function Stat({ label, value, rule = 'yellow' }: {
  label: string
  value: ReactNode
  rule?: 'pink' | 'green' | 'yellow' | 'blue'
}) {
  return (
    <div className={s.stat}>
      <div className={`${s.statLabel} t-label-sm`}>{label}</div>
      <div className={`${s.statValue} t-display-md`}>{value}</div>
      <div className={`${s.statRule} ${s[`rule_${rule}`]}`} aria-hidden />
    </div>
  )
}

export const StatStrip = ({ children }: { children: ReactNode }) =>
  <div className={s.statStrip}>{children}</div>

export function Button({ variant = 'filled', size = 'md', children, ...rest }:
  { variant?: 'filled' | 'outline' | 'quiet'; size?: 'md' | 'sm' } &
  ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button className={`${s.btn} ${s[`btn_${variant}`]} ${s[`btn_${size}`]} t-label-md`} {...rest}>
      {children}
    </button>
  )
}

export function FilterPill({ active = false, children, ...rest }:
  { active?: boolean } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button className={`${s.filter} ${active ? s.filterOn : ''} t-label-md`} {...rest}>
      {children}
    </button>
  )
}

export function EmptyState({ icon, title, body, action }: {
  icon?: ReactNode
  title: string
  body?: string
  action?: ReactNode
}) {
  return (
    <div className={s.empty}>
      {icon && <div className={s.emptyIcon} aria-hidden>{icon}</div>}
      <p className={`${s.emptyTitle} t-heading-sm`}>{title}</p>
      {body && <p className={`${s.emptyBody} t-body-md`}>{body}</p>}
      {action}
    </div>
  )
}

/** Table rows are a 64px pitch with a hairline between them. */
export function Table({ columns, children }: { columns: string[]; children: ReactNode }) {
  return (
    <div className={s.table} role="table">
      <div className={s.thead} role="row">
        {columns.map((c) => (
          <span key={c} className="t-overline" role="columnheader">{c}</span>
        ))}
      </div>
      {children}
    </div>
  )
}

export const Row = ({ children }: { children: ReactNode }) =>
  <div className={s.row} role="row">{children}</div>
