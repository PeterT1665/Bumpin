import type { ReactNode } from 'react'
import { Outlet } from 'react-router-dom'
import { NavRail } from './NavRail'
import { ArrivalToast, useArrivals } from './Arrivals'
import { SearchProvider, useSearch } from './search'
import styles from './AppShell.module.css'

/** Brown backdrop, cream window inset 56px, rail on the left, canvas on the
 *  right. Identical on every screen — see the Figma frames. */
export function AppShell() {
  const { badges, toast, dismiss } = useArrivals()
  return (
    <div className={styles.backdrop}>
      {toast && <ArrivalToast ticket={toast} onClose={dismiss} />}
      <div className={styles.window}>
        <NavRail badges={badges} />
        <main className={styles.canvas}>
          {/* Inside the window so every screen's top bar shares one query. */}
          <SearchProvider>
            <Outlet />
          </SearchProvider>
        </main>
      </div>
    </div>
  )
}

export function TopBar({ title, children, placeholder, searchable = true }: {
  title: string
  children?: ReactNode
  /** Screens name what their own search actually looks at. */
  placeholder?: string
  /** A screen with no list to narrow passes false. A box that accepts typing and
   *  changes nothing is worse than no box. */
  searchable?: boolean
}) {
  const { q, setQ } = useSearch()
  return (
    <header className={styles.topbar}>
      <h1 className={`${styles.title} t-display-md`}>{title}</h1>
      {children}
      <div className={styles.tools}>
        {searchable && (
          <label className={styles.search}>
            <svg viewBox="0 0 16 16" width="14" height="14" fill="none"
                 stroke="currentColor" strokeWidth="1.5" aria-hidden>
              <circle cx="6.5" cy="6.5" r="5.5" />
              <path d="M10.5 10.5 L15 15" strokeLinecap="round" />
            </svg>
            <input placeholder={placeholder ?? 'Search tickets, artists, vendors'}
                   aria-label="Search" value={q}
                   onChange={(e) => setQ(e.target.value)} />
            {q !== '' && (
              <button type="button" className={styles.clear} aria-label="Clear search"
                      onClick={() => setQ('')}>&#215;</button>
            )}
          </label>
        )}
        <div className={styles.avatar} title="Ravi">RA</div>
      </div>
    </header>
  )
}
