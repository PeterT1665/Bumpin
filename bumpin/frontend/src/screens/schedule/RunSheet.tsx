import { useMemo, useState } from 'react'
import { TopBar } from '@/components/AppShell'
import { Button, FilterPill, Row, Stat, StatusPill, Table } from '@/components/primitives'
import { matches, useSearch } from '@/components/search'
import { ApiError, api } from '@/api/client'
import type { NewSet, RunsheetRow } from '@/api/types'
import {
  AddPanel, Cell, ChipCell, ControlsRow, Field, Name, Plain, Quiet, RemoveCell,
  TableCard, TableEmpty, TableNoMatches, TableNotice, cols, control, entered,
  rowNote, tabs, useResource,
} from './kit'
import { kindLabel, longDay, needsFor, statusPill, timeRange } from './derive'

/* Figma 212:2, table card 214:2. Columns, pitch and chip geometry are
   transcribed there; the backend gaps are called out where they bite. */

/* The trailing '' is the remove control's column. The design's table ends at
   'Changed' (212:2); the header for a control needs no word over it. */
const COLUMNS = ['Time', 'Who', 'Needs', 'Stage or zone', 'Status', 'Contact', 'Changed', '']

const SUB =
  'Sets and load-ins in one order, built from the artist and vendor records. ' +
  'Needs are the approved technical rider.'

/** A set needs four things and no more: who is playing, where, and between
 *  which two times. Everything starts empty so the endpoint can name the field
 *  that is missing rather than a default silently standing in for it. */
const BLANK = { artist: '', stage: '', start: '', end: '' }

export function RunSheet() {
  // `/runsheet` has no day parameter, so every row arrives and the tabs filter
  // here. Inventory is fetched alongside it only to rebuild the Needs column,
  // and artists and stages only to populate the new-row form.
  const [sheet, reloadSheet] = useResource(api.runsheet)
  const [stock] = useResource(api.inventory)
  const [roster, reloadRoster] = useResource(api.artists)
  const [stages] = useResource(api.stages)
  const [day, setDay] = useState<string | null>(null)
  /* The top bar owns the query; holding a copy here would survive navigation
     and silently hide rows on the next screen. */
  const { q } = useSearch()
  const filtering = q.trim() !== ''

  const rows: RunsheetRow[] = sheet.status === 'ready' ? sheet.data : []
  const inventory = stock.status === 'ready' ? stock.data : []

  const [draft, setDraft] = useState(BLANK)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  /* Removing is tracked per row, not by one shared flag: the operator can be
     shown which row is in flight, and a refusal on one row must not grey out
     the rest of the table. */
  const [removing, setRemoving] = useState<number | null>(null)
  const [removeError, setRemoveError] = useState<string | null>(null)

  /* Who can be added is not a free-text name: this screen is "built from the
     artist and vendor records", as the note under its own title says, so a set
     row is an applicant finally given a slot. Anyone already holding one is
     already a row. */
  const waiting = useMemo(
    () => (roster.status === 'ready' ? roster.data : []).filter((a) => a.set_start === null),
    [roster],
  )

  // Tab labels come from the data in the order the backend returns them, which
  // is already chronological: Fri 11 Dec / Sat 12 Dec / Sun 13 Dec. They are
  // read off every row, not the matched ones, so the festival keeps all three
  // days while a query narrows what sits under them.
  const days = useMemo(() => [...new Set(rows.map((r) => r.day))], [rows])

  /* Everything the query leaves standing, across all days. The status and kind
     are matched through the same labels the row draws, so "Confirmed" and
     "Load-in" find rows that the raw `completed` / `load_in` would not. */
  const matched = useMemo(
    () => rows.filter((r) => matches(
      q, r.who, r.area, r.contact, statusPill(r.status).label, kindLabel(r.kind),
    )),
    [rows, q],
  )

  // The operator's tab wins, unless the query has emptied it and another day
  // still has hits — otherwise a match two tabs over is invisible.
  const chosen = day !== null && days.includes(day) ? day : days[0] ?? null
  const active = chosen !== null && !matched.some((r) => r.day === chosen)
    ? matched[0]?.day ?? chosen
    : chosen

  const onDay = useMemo(() => rows.filter((r) => r.day === active), [rows, active])
  const shown = useMemo(() => matched.filter((r) => r.day === active), [matched, active])

  // "Sets today" counts the selected day; "Load-ins" carries no "today" in the
  // design (212:443) and is the festival-wide figure. Both report the whole
  // sheet, not the search — the note under the card title says as much.
  const setsToday = onDay.filter((r) => r.kind === 'set').length
  const loadIns = rows.filter((r) => r.kind === 'load_in').length

  const title = onDay.length ? longDay(onDay[0].start) : (active ?? 'Run sheet')

  /* Opening the form on a day tab means adding a set to THAT day, so the two
     times start on it. An evening hour only because that is where the sets on
     this festival sit; the operator overwrites both. */
  function openForm() {
    const date = onDay[0]?.start.slice(0, 10) ?? ''
    setDraft({
      ...BLANK,
      start: date && `${date}T18:00`,
      end: date && `${date}T19:00`,
    })
    setError(null)
    setOpen(true)
  }

  async function add() {
    setBusy(true)
    setError(null)
    const body: NewSet = {
      artist_id: entered(draft.artist),
      stage_id: entered(draft.stage),
      start: draft.start,
      end: draft.end,
    }
    try {
      await api.addSet(body)
      setDraft(BLANK)
      setOpen(false)
      /* The sheet gains a row and the roster loses an applicant, so both have to
         be refetched or the artist stays in the select that just scheduled her. */
      reloadSheet()
      reloadRoster()
    } catch (err: unknown) {
      setError(err instanceof ApiError ? err.detail : 'The set could not be added.')
    } finally {
      setBusy(false)
    }
  }

  /** Takes an artist back off the sheet. The artist stays on file — only the
   *  slot goes — so they reappear in the select above, which is why the roster
   *  is refetched alongside the sheet. */
  async function remove(artistId: number) {
    setRemoving(artistId)
    setRemoveError(null)
    try {
      await api.removeSet(artistId)
      reloadSheet()
      reloadRoster()
    } catch (err: unknown) {
      setRemoveError(err instanceof ApiError ? err.detail : 'That set could not be removed.')
    } finally {
      setRemoving(null)
    }
  }

  return (
    <>
      <TopBar title="Run sheet" placeholder="Search who, stage, status or contact" />

      <ControlsRow
        left={
          <>
            <div className={tabs} aria-label="Day">
              {days.map((d) => (
                <FilterPill
                  key={d}
                  aria-pressed={d === active}
                  active={d === active}
                  onClick={() => setDay(d)}
                >
                  {d}
                </FilterPill>
              ))}
            </div>
            <Button
              variant="outline"
              aria-expanded={open}
              onClick={() => (open ? setOpen(false) : openForm())}
            >
              {open ? 'Close' : 'Add set'}
            </Button>
          </>
        }
        stats={
          <>
            <Stat label="Sets today" value={setsToday} rule="yellow" />
            {/* Nothing records that a row moved, so this cannot be counted —
                see the note on the Changed column below. */}
            <Stat label="Changed today" value="—" rule="pink" />
            <Stat label="Load-ins" value={loadIns} rule="green" />
          </>
        }
      />

      <TableCard
        title={title}
        sub={SUB}
        note={removeError
          ? <span className={rowNote}>{removeError}</span>
          : filtering && sheet.status === 'ready'
            ? `Showing ${shown.length} of ${onDay.length} rows on this day. ` +
              'The stats above count the whole day.'
            : undefined}
        cols={cols.runsheet}
        form={open && (
          <AddPanel
            title="New set"
            submit="Add set"
            error={error}
            busy={busy}
            onSubmit={add}
            onCancel={() => { setOpen(false); setError(null); setDraft(BLANK) }}
          >
            <Field label="Who" grow={3}>
              <select
                className={control} value={draft.artist} autoFocus
                onChange={(e) => setDraft({ ...draft, artist: e.target.value })}
              >
                <option value="">
                  {/* An empty roster is worth saying out loud: the control is the
                      only place the operator could learn there is nobody left. */}
                  {waiting.length ? 'Choose…' : 'Every applicant already has a slot'}
                </option>
                {waiting.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </Field>
            <Field label="Stage" grow={2}>
              <select
                className={control} value={draft.stage}
                onChange={(e) => setDraft({ ...draft, stage: e.target.value })}
              >
                <option value="">Choose…</option>
                {(stages.status === 'ready' ? stages.data : []).map((st) => (
                  <option key={st.id} value={st.id}>{st.name}</option>
                ))}
              </select>
            </Field>
            {/* datetime-local already emits "2026-12-12T18:00", which is the form
                every other timestamp in the schedule is stored in. */}
            <Field label="Starts" grow={2}>
              <input
                className={control} value={draft.start} type="datetime-local"
                onChange={(e) => setDraft({ ...draft, start: e.target.value })}
              />
            </Field>
            <Field label="Ends" grow={2}>
              <input
                className={control} value={draft.end} type="datetime-local"
                onChange={(e) => setDraft({ ...draft, end: e.target.value })}
              />
            </Field>
          </AddPanel>
        )}
      >
        <Table columns={COLUMNS}>
          {sheet.status === 'loading' && <TableNotice title="Loading the run sheet…" />}
          {sheet.status === 'error' && (
            <TableNotice title="The run sheet could not be loaded" body={sheet.message} />
          )}
          {/* An empty sheet and a sheet emptied by the search are different
              states: every day tab comes from a row, so a day can only be empty
              because the query hid it. */}
          {sheet.status === 'ready' && shown.length === 0 && (
            rows.length === 0 ? <TableEmpty /> : <TableNoMatches query={q} noun="rows" />
          )}
          {shown.map((r) => {
            const status = statusPill(r.status)
            const needs = needsFor(r, inventory)
            return (
              <Row key={`${r.start}-${r.area}-${r.who}`}>
                <Plain>{timeRange(r.start, r.end)}</Plain>
                <Name>{r.who}</Name>
                {needs ? <Plain>{needs}</Plain> : <Cell />}
                <Plain>{r.area}</Plain>
                <ChipCell><StatusPill label={status.label} tone={status.tone} /></ChipCell>
                <Quiet>{r.contact ?? ''}</Quiet>
                {/* The design puts a "Changed" chip here on rows an approved
                    action moved (Figma 218:10). The backend records no such
                    flag, so the column renders and stays empty rather than
                    guessing. The chip it would carry, once there is something
                    to read, is exactly this one. */}
                <ChipCell />
                {/* A vendor load-in carries no artist_id, so it renders an
                    empty cell: that window lives on the vendor record and is
                    moved by approving the vendor's ticket, not from here. */}
                <RemoveCell
                  label={`Take ${r.who} off the run sheet`}
                  busy={removing === r.artist_id}
                  onRemove={r.artist_id === null ? undefined : () => void remove(r.artist_id as number)}
                />
              </Row>
            )
          })}
        </Table>
      </TableCard>
    </>
  )
}
