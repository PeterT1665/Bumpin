import {
  createContext, useContext, useEffect, useMemo, useState, type ReactNode,
} from 'react'
import { useLocation } from 'react-router-dom'

/* The search box lives in the top bar (AppShell) but the lists it filters live
   in the screens, so the query is held here and read with `useSearch()`.
   It resets on navigation: a query typed on one screen would otherwise hide
   rows on the next one with no visible cause. */

type Search = { q: string; setQ: (v: string) => void }

const Ctx = createContext<Search>({ q: '', setQ: () => {} })

export function SearchProvider({ children }: { children: ReactNode }) {
  const [q, setQ] = useState('')
  const { pathname } = useLocation()
  useEffect(() => { setQ('') }, [pathname])
  const value = useMemo(() => ({ q, setQ }), [q])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSearch() {
  return useContext(Ctx)
}

/** True when the query is empty, or when any field contains it.
 *  Case- and whitespace-insensitive; non-string fields are skipped. */
export function matches(q: string, ...fields: (string | number | null | undefined)[]) {
  const needle = q.trim().toLowerCase()
  if (needle === '') return true
  return fields.some((f) => f !== null && f !== undefined && String(f).toLowerCase().includes(needle))
}
