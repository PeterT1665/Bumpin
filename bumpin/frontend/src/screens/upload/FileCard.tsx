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
    </article>
  )
}
