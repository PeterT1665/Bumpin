import { NavLink } from 'react-router-dom'
import styles from './NavRail.module.css'

/* Icon paths are transcribed from the Figma nav rail vectors. Each is drawn in
   its own small viewBox at the size it is drawn in the design, then scaled. */

const Dashboard = () => (
  <svg viewBox="-0.75 -0.75 19.5 19.5" width="18" height="18" fill="none"
       stroke="currentColor" strokeWidth="1.5">
    <rect x="0" y="0" width="7" height="7" rx="1.5" />
    <rect x="11" y="0" width="7" height="7" rx="1.5" />
    <rect x="0" y="11" width="7" height="7" rx="1.5" />
    <rect x="11" y="11" width="7" height="7" rx="1.5" />
  </svg>
)

const Riders = () => (
  <svg viewBox="-0.75 -0.75 17.5 20.5" width="16" height="19" fill="none"
       stroke="currentColor" strokeWidth="1.5">
    <ellipse cx="8" cy="3.5" rx="3.5" ry="3.5" />
    <rect x="0" y="10" width="16" height="9" rx="4" />
  </svg>
)

const Vendors = () => (
  <svg viewBox="-0.75 -0.75 19.5 14.5" width="18" height="13" fill="none"
       stroke="currentColor" strokeWidth="1.5">
    <rect x="0" y="0" width="18" height="11" rx="3" />
    <path d="M 3 3 L 15 3" />
    <circle cx="6" cy="11" r="2" fill="currentColor" stroke="none" />
    <circle cx="13" cy="11" r="2" fill="currentColor" stroke="none" />
  </svg>
)

const RunSheet = () => (
  <svg viewBox="-0.75 -0.75 17.5 13.5" width="16" height="12" fill="none"
       stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
    <path d="M 0 1 L 3 1 M 6 1 L 16 1 M 0 6 L 3 6 M 6 6 L 16 6 M 0 11 L 3 11 M 6 11 L 16 11" />
  </svg>
)

const Equipment = () => (
  <svg viewBox="-0.75 -0.75 17.5 13.5" width="16" height="12" fill="none"
       stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
    <path d="M 0 2 L 16 2 L 16 12 L 0 12 Z M 0 5.5 L 16 5.5 M 6 2 L 6 0 L 10 0 L 10 2" />
  </svg>
)

const Upload = () => (
  <svg viewBox="-0.75 -0.75 17.5 12.5" width="16" height="11" fill="none"
       stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M 0 7 L 0 11 L 16 11 L 16 7 M 8 9 L 8 0 M 8 0 L 4 4 M 8 0 L 12 4" />
  </svg>
)

/** Order matches the design: dashboard, riders, vendors, run sheet, equipment,
 *  upload. Detail screens light their parent section. */
export const NAV = [
  { to: '/', label: 'Overview', Icon: Dashboard, end: true },
  { to: '/riders', label: 'Rider needs', Icon: Riders, end: false },
  { to: '/vendors', label: 'Vendors', Icon: Vendors, end: false },
  { to: '/runsheet', label: 'Run sheet', Icon: RunSheet, end: false },
  { to: '/equipment', label: 'Equipment', Icon: Equipment, end: false },
  { to: '/upload', label: 'Upload', Icon: Upload, end: false },
] as const

/** `badges` counts tickets that arrived while the app was open, by section. */
export function NavRail({ badges = {} }: { badges?: Partial<Record<string, number>> }) {
  return (
    <nav className={styles.rail} aria-label="Sections">
      <div className={styles.mark} aria-hidden>
        <svg viewBox="0 0 40 32" width="40" height="32" fill="currentColor">
          {/* Mainstage mark, transcribed verbatim from Figma vector 86:10.
              Module grid of 8px cells with 1.2px fillets on convex AND concave
              corners — that equal filleting is the whole character of the mark,
              so this path must not be redrawn by hand. */}
          <path
            fillRule="evenodd"
            d="M 8 1.2 C 8 0.54 8.54 0 9.2 0 L 30.8 0 C 31.46 0 32 0.54 32 1.2 L 32 6.8 C 32 7.46 32.54 8 33.2 8 L 38.8 8 C 39.46 8 40 8.54 40 9.2 L 40 30.8 C 40 31.46 39.46 32 38.8 32 L 33.2 32 C 32.54 32 32 31.46 32 30.8 L 32 17.2 C 32 16.54 31.46 16 30.8 16 L 25.2 16 C 24.54 16 24 15.46 24 14.8 L 24 9.2 C 24 8.54 23.46 8 22.8 8 L 17.2 8 C 16.54 8 16 8.54 16 9.2 L 16 14.8 C 16 15.46 15.46 16 14.8 16 L 9.2 16 C 8.54 16 8 16.54 8 17.2 L 8 30.8 C 8 31.46 7.46 32 6.8 32 L 1.2 32 C 0.54 32 0 31.46 0 30.8 L 0 9.2 C 0 8.54 0.54 8 1.2 8 L 6.8 8 C 7.46 8 8 7.46 8 6.8 L 8 1.2 Z"
          />
        </svg>
      </div>

      <ul className={styles.items}>
        {NAV.map(({ to, label, Icon, end }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) => (isActive ? `${styles.item} ${styles.active}` : styles.item)}
              title={label}
            >
              <span className={styles.pill} aria-hidden />
              <span className={styles.glyph}><Icon /></span>
              {badges[to] ? <span className={styles.badge}>{badges[to]}</span> : null}
              <span className={styles.srOnly}>{badges[to] ? `${label}, ${badges[to]} new` : label}</span>
            </NavLink>
          </li>
        ))}
      </ul>

      <div className={styles.avatar} title="Ravi">RA</div>
    </nav>
  )
}
