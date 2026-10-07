import { Button } from '@/components/primitives'
import type { Finding, ProposedAction, Severity } from '@/api/types'
import { HIGHLIGHT_TONE, kindLabel } from './riders'
import s from './cards.module.css'

/* Figma 121:2 / 191:2 (one finding) and 199:2 -> 200:3 / 201:3 / 202:3 / 203:15
   (the list of independently approvable actions). */

/** 191:2 is a warning and offers only "I understand"; 121:2 is a conflict and
 *  offers Resolve / Ignore. Both carry the severity tag.
 *
 *  Resolve is a write before it is a dialog — it marks the finding resolved and
 *  drafts the reply — so it carries its own busy label and shows a refusal here
 *  rather than opening an empty email panel.
 *
 *  "I understand" writes NOTHING. It used to call the same ignore that the
 *  conflict card's Ignore does, which marked the finding ignored and took its
 *  highlight off the page: one click, directly under a card that had just
 *  opened under the pointer, and the yellow box the operator was reading was
 *  gone. A low-capacity flag is a heads-up, not a decision — acknowledging it
 *  only puts the card away. */
export function FindingCard({ finding, active, onResolve, onIgnore, onAcknowledge, busy, resolving, error }: {
  finding: Finding
  active: boolean
  onResolve: () => void
  onIgnore: () => void
  onAcknowledge: () => void
  busy: boolean
  resolving?: boolean
  error?: string | null
}) {
  const tone = HIGHLIGHT_TONE[finding.severity]
  const isConflict = finding.severity === 'conflict'

  return (
    <section className={`${s.shell} ${active ? s.shellActive : ''}`}>
      <div className={s.finding}>
        <div className={s.head}>
          <span className={`${s.headLabel} t-label-md`}>
            {isConflict ? 'Bumpin suggests' : 'Bumpin flags this'}
          </span>
          <span className={`${s.tag} ${s[`tag_${tone}`]} t-caption`}>{kindLabel(finding.kind)}</span>
        </div>
        <p className={`${s.findingBody} t-body-sm`}>{finding.suggestion || finding.message}</p>
        {error && (
          <div className={s.errorSlot}>
            <p className={`${s.error} t-caption`} role="alert">{error}</p>
          </div>
        )}
        <div className={s.findingFoot}>
          {isConflict ? (
            <>
              {/* 121:7 is 104 wide, 121:9 is 92 — both hand-set in the mock. */}
              <Button variant="filled" onClick={onResolve} disabled={busy} style={{ minWidth: 104 }}>
                {resolving ? 'Resolving…' : 'Resolve'}
              </Button>
              <Button variant="outline" onClick={onIgnore} disabled={busy} style={{ minWidth: 92 }}>
                Ignore
              </Button>
            </>
          ) : (
            /* 191:7 is 128 wide. */
            <Button variant="outline" onClick={onAcknowledge} style={{ minWidth: 128 }}>
              I understand
            </Button>
          )}
        </div>
      </div>
    </section>
  )
}

export type RowError = { index: number; message: string }

/** 200:3 and its three sibling states.
 *
 *  Approving one action writes the schedule change straight away and drafts one
 *  email — it does not send — so the list is a mix of approved and still
 *  proposed rows, and the ticket is `in_progress` until every row is approved.
 *  A row that comes back refused keeps its message inline and makes Edit the
 *  primary button, exactly as 202:3 draws it. */
export function ChangeActionsCard({
  summary, severity, actions, error, busy, active,
  onApprove, onDeny, onApproveAll, onViewDraft,
}: {
  summary: string
  severity: Severity
  actions: ProposedAction[]
  error: RowError | null
  busy: number | 'all' | null
  active?: boolean
  onApprove: (index: number) => void
  onDeny: (index: number) => void
  onApproveAll: () => void
  onViewDraft: (outboxId: number) => void
}) {
  const anyProposed = actions.some((a) => a.status === 'proposed')

  return (
    <section className={`${s.shell} ${active ? s.shellActive : ''}`}>
      <div className={s.list}>
        <div className={s.intro}>
          <div className={s.head}>
            <span className={`${s.headLabel} t-label-md`}>Bumpin suggests</span>
            <span className={`${s.tag} ${s[`tag_${HIGHLIGHT_TONE[severity]}`]} t-caption`}>
              {kindLabel('schedule_change')}
            </span>
          </div>
          <p className={`${s.introBody} t-body-sm`}>{summary}</p>
        </div>

        <div className={s.rows}>
          <div className={s.divider} aria-hidden />
          {actions.map((a) => {
            const done = a.status !== 'proposed'
            const denied = a.status === 'denied'
            const failed = error?.index === a.index
            return (
              <div key={a.index}>
                <div className={`${s.row} ${failed ? s.rowBlocked : ''}`}>
                  <div className={s.copy}>
                    <p className={`${s.rowTitle} ${done ? s.rowTitleDone : ''} t-label-md`}>{a.title}</p>
                    <p className={`${s.rowDetail} t-caption`}>{a.detail}</p>
                    {failed && (
                      <div className={s.errorSlot}>
                        <p className={`${s.error} t-caption`} role="alert">{error.message}</p>
                      </div>
                    )}
                  </div>

                  {done ? (
                    <div className={s.rowStatus}>
                      <span className={`${s.approvedBy} t-label-sm`}>
                        {denied ? 'Denied' : 'Approved'} by{' '}
                        {a.approved_by ? cap(a.approved_by) : 'someone'}
                      </span>
                      {a.outbox_id !== null && (
                        <button type="button" className={`${s.viewDraft} t-label-sm`}
                                onClick={() => onViewDraft(a.outbox_id as number)}>
                          View draft
                        </button>
                      )}
                    </div>
                  ) : (
                    <div className={s.rowActions}>
                      <button type="button"
                              className={`${s.pillBtn} ${failed ? s.pillOutline : s.pillFilled} t-label-sm`}
                              disabled={busy !== null}
                              onClick={() => onApprove(a.index)}>
                        Approve
                      </button>
                      <button type="button"
                              className={`${s.pillBtn} ${s.pillOutline} t-label-sm`}
                              disabled={busy !== null}
                              onClick={() => onDeny(a.index)}>
                        Deny
                      </button>
                    </div>
                  )}
                </div>

                <div className={s.divider} aria-hidden />
              </div>
            )
          })}
        </div>

        <div className={s.listFoot}>
          <button type="button" className={`${s.approveAll} t-label-md`}
                  disabled={!anyProposed || busy !== null} onClick={onApproveAll}>
            Approve all
          </button>
        </div>
      </div>
    </section>
  )
}

const cap = (x: string) => x.charAt(0).toUpperCase() + x.slice(1)

