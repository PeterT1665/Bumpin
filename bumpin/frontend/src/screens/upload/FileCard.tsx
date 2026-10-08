import type { UploadedFile } from './files'
import { formatDate, formatSize } from './files'
import s from './Upload.module.css'

/** 113:81 and its five siblings. The card is the Card primitive's fill, border,
 *  radius and shadow, but at 20px padding and a 16px gap rather than the
 *  primitive's 26/28 — so it is built here rather than reusing Card. */
export function FileCard({ file, onRemove }: {
  file: UploadedFile
  onRemove: (id: string) => void
}) {
  return (
    <article className={s.card}>
      <div className={s.titleRow}>
        <h3 className={`${s.filename} t-heading-sm`}>{file.name}</h3>
        <button
          type="button"
          className={`${s.menu} t-body-md-b`}
          onClick={() => onRemove(file.id)}
          aria-label={`Remove ${file.name}`}
          title={`Remove ${file.name}`}
        >
          •••
        </button>
      </div>
      <div className={s.footer}>
        <span className={`${s.badge} t-label-sm`}>{file.format}</span>
        <div className={s.meta}>
          <p className={`${s.metaMain} t-body-md-b`}>
            {formatSize(file.size)} · {file.docType}
          </p>
          <p className={`${s.metaDate} t-body-sm`}>{formatDate(file.uploadedAt)}</p>
        </div>
      </div>
      <Outcome file={file} />
    </article>
  )
}

/** What the backend did with the file. */
function Outcome({ file }: { file: UploadedFile }) {
  if (!file.status) return null
  if (file.status === 'reading') return <p className={`${s.outcome} t-label-sm`}>Reading…</p>
  const r = file.result
  if (file.status === 'failed' || !r) {
    return <p className={`${s.outcome} ${s.outcomeFail} t-label-sm`}>{r?.summary ?? 'Could not upload this file.'}</p>
  }
  if (r.stored_as === 'equipment' && r.equipment) {
    const { added, updated, unchanged } = r.equipment
    const parts = [
      added && `${added} added`, updated && `${updated} updated`, unchanged && `${unchanged} already on file`,
    ].filter(Boolean)
    return (
      <div className={`${s.outcome} ${s.outcomeEquip}`}>
        <p className="t-label-sm">Equipment: {parts.join(', ') || 'nothing to add'}</p>
        {r.riders_rechecked ? <p className="t-caption">{r.riders_rechecked} riders re-checked against it</p> : null}
      </div>
    )
  }
  return (
    <div className={`${s.outcome} ${s.outcomeMemory}`}>
      <p className="t-label-sm">Saved to Bumpin's memory</p>
      <p className="t-caption">{r.summary}</p>
    </div>
  )
}
