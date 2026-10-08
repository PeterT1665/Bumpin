import { useMemo, useState } from 'react'
import { TopBar } from '@/components/AppShell'
import { Button, Chip, FilterPill, Row, Stat, Table } from '@/components/primitives'
import { matches, useSearch } from '@/components/search'
import { ApiError, api } from '@/api/client'
import type { NewInventoryItem } from '@/api/types'
import {
  AddPanel, ChipCell, ControlsRow, Field, Name, Nothing, Plain, RemoveCell,
  TableCard, TableEmpty, TableNoMatches, TableNotice, cols, control, entered,
  freeChip, rowNote, useResource,
} from './kit'
import { itemRows } from './derive'

/* Figma 224:147, table card 224:206. Reserved and Free are arithmetic over
   `/inventory` — the backend sends neither. */

/* The trailing '' is the remove control's column. The design's table ends at
   'Flag' (224:147); the header for a control needs no word over it. */
const COLUMNS = [
  'Item', 'Category', 'Stage or pool', 'Total', 'Reserved', 'Free', 'Held by', 'Flag', '',
]

const SUB =
  'Reserved quantities come from approved riders. Free is total minus reserved, ' +
  'recomputed whenever a rider is approved or a set moves.'

/** What a row needs and nothing more. The stage is a real choice, so it starts
 *  on the shared pool rather than unset; everything else starts empty so the
 *  endpoint can say which field is missing. */
const BLANK = { name: '', category: '', stage: '', quantity: '' }

export function Equipment() {
  const [stock, reloadStock] = useResource(api.inventory)
  const [stages] = useResource(api.stages)
  const inventory = stock.status === 'ready' ? stock.data : []
  /* The top bar owns the query; a local copy would outlive this screen. */
  const { q } = useSearch()
  const filtering = q.trim() !== ''

  const [draft, setDraft] = useState(BLANK)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  /* Per row, so the operator can see which one is in flight and a refusal on
     one item does not grey out the rest of the table. */
  const [removing, setRemoving] = useState<number | null>(null)
  const [removeError, setRemoveError] = useState<string | null>(null)

  /* Offered rather than typed: Category is a column readers scan and search, so
     a second spelling of "audio" would split it in two. */
  const categories = useMemo(
    () => [...new Set(inventory.map((i) => i.category))].sort(),
    [inventory],
  )

  async function add() {
    setBusy(true)
    setError(null)
    const body: NewInventoryItem = {
      canonical_name: draft.name,
      category: draft.category,
      // "" is the shared pool, which the endpoint reads as a null stage.
      stage_id: draft.stage === '' ? null : Number(draft.stage),
      quantity_total: entered(draft.quantity),
    }
    try {
      await api.addInventoryItem(body)
      setDraft(BLANK)
      setOpen(false)
      reloadStock()
    } catch (err: unknown) {
      /* The endpoint refused, and its detail is the sentence to show. Anything
         else is the request itself failing, which is not about this row. */
      setError(err instanceof ApiError ? err.detail : 'The item could not be added.')
    } finally {
      setBusy(false)
    }
  }

  /** The mirror of `add`. An item an approved rider has reserved is refused by
   *  the endpoint rather than deleted out from under the reservation. */
  async function remove(itemId: number) {
    setRemoving(itemId)
    setRemoveError(null)
    try {
      await api.removeInventoryItem(itemId)
      reloadStock()
    } catch (err: unknown) {
      setRemoveError(err instanceof ApiError ? err.detail : 'That item could not be removed.')
    } finally {
      setRemoving(null)
    }
  }

  // Server order is kept: it already groups River / Lawn / Dome / shared pool,
  // and the mock's within-group order follows no rule that can be read off it.
  const items = useMemo(() => itemRows(inventory), [inventory])

  /* Name, category and stage — the three columns a reader would scan. `where`
     is matched rather than `stage_name`, so "shared" finds the pool items that
     have no stage at all. Filtering after itemRows keeps the server's grouping:
     the matched rows stay in the same order the unfiltered table drew them. */
  const shown = useMemo(
    () => items.filter((i) => matches(q, i.name, i.category, i.where)),
    [items, q],
  )

  // The stats are the whole inventory, not the search — Free and Reserved only
  // mean anything against every item, so the note under the title says so.
  const fullyBooked = items.filter((i) => i.free <= 0).length
  const conflicts = items.filter((i) => i.flag !== null).length

  return (
    <>
      <TopBar title="Equipment" placeholder="Search item, category or stage" />

      <ControlsRow
        left={
          <>
            {/* Figma 228:2 — one pill, in its selected state. There is no second
                option in the design, so there is no second option here. */}
            <FilterPill active aria-pressed>All stages</FilterPill>
            <Button
              variant="outline"
              aria-expanded={open}
              onClick={() => { setOpen(!open); setError(null) }}
            >
              {open ? 'Close' : 'Add item'}
            </Button>
          </>
        }
        stats={
          <>
            <Stat label="Items" value={items.length} rule="yellow" />
            <Stat label="Fully booked" value={fullyBooked} rule="green" />
            <Stat label="Conflicts" value={conflicts} rule="pink" />
          </>
        }
      />

      <TableCard
        title="Inventory"
        sub={SUB}
        note={removeError
          ? <span className={rowNote}>{removeError}</span>
          : filtering && stock.status === 'ready'
            ? `Showing ${shown.length} of ${items.length} items. ` +
              'The stats above count the whole inventory.'
            : undefined}
        cols={cols.equipment}
        form={open && (
          <AddPanel
            title="New inventory item"
            submit="Add item"
            error={error}
            busy={busy}
            onSubmit={add}
            onCancel={() => { setOpen(false); setError(null); setDraft(BLANK) }}
          >
            <Field label="Item" grow={3}>
              <input
                className={control} value={draft.name} autoFocus
                placeholder="Wedge monitor"
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </Field>
            <Field label="Category" grow={2}>
              <select
                className={control} value={draft.category}
                onChange={(e) => setDraft({ ...draft, category: e.target.value })}
              >
                <option value="">Choose…</option>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>
            <Field label="Stage or pool" grow={2}>
              <select
                className={control} value={draft.stage}
                onChange={(e) => setDraft({ ...draft, stage: e.target.value })}
              >
                {/* Figma 228:125 — an item with no stage reads "Shared pool". */}
                <option value="">Shared pool</option>
                {(stages.status === 'ready' ? stages.data : []).map((st) => (
                  <option key={st.id} value={st.id}>{st.name}</option>
                ))}
              </select>
            </Field>
            <Field label="Total">
              <input
                className={control} value={draft.quantity}
                type="number" min={1} step={1} inputMode="numeric"
                onChange={(e) => setDraft({ ...draft, quantity: e.target.value })}
              />
            </Field>
          </AddPanel>
        )}
      >
        <Table columns={COLUMNS}>
          {stock.status === 'loading' && <TableNotice title="Loading the inventory…" />}
          {stock.status === 'error' && (
            <TableNotice title="The inventory could not be loaded" body={stock.message} />
          )}
          {/* An empty inventory and an inventory emptied by the search are two
              different things, and only the first is worth an upload prompt. */}
          {stock.status === 'ready' && shown.length === 0 && (
            items.length === 0 ? <TableEmpty /> : <TableNoMatches query={q} noun="items" />
          )}
          {shown.map((i) => (
            <Row key={i.key}>
              <Name>{i.name}</Name>
              <Plain>{i.category}</Plain>
              <Plain>{i.where}</Plain>
              <Plain>{i.total}</Plain>
              <Plain>{i.reserved}</Plain>
              {/* Figma 228:28 ("Free none") — nothing free reads as the
                  number in a pink-soft chip, pulled 8px left so the numeral
                  stays in column. Over-allocation takes the chip too. */}
              {i.free <= 0
                ? <ChipCell className={freeChip}><Chip tone="pink">{i.free}</Chip></ChipCell>
                : <Plain>{i.free}</Plain>}
              {i.heldBy.length ? <Name>{i.heldBy.join(', ')}</Name> : <Nothing />}
              {/* Figma 228:31 / 228:131. Both flags are arithmetic over the
                  allocations: Shortage when more is reserved than exists,
                  Clash when two artists hold the same item at the same time.
                  The mock's two flagged rows come from rider demand that no
                  endpoint exposes, so neither fires on today's data. */}
              <ChipCell>{i.flag && <Chip tone="pink">{i.flag}</Chip>}</ChipCell>
              {/* Reserved quantities are the backend's to refuse, not this
                  screen's to pre-empt: the button is always offered and the
                  endpoint answers with the sentence to show. */}
              <RemoveCell
                label={`Remove ${i.name} from the inventory`}
                busy={removing === i.id}
                onRemove={() => void remove(i.id)}
              />
            </Row>
          ))}
        </Table>
      </TableCard>
    </>
  )
}
