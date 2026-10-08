import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { TopBar } from '@/components/AppShell'
import { Button, Chip } from '@/components/primitives'
import { DropZone, UploadGlyph } from './DropZone'
import { FileCard } from './FileCard'
import { api } from '@/api/client'
import {
  ACCEPT_ATTR, SUPPORTED_FORMATS,
  acceptFiles, docTypeOfKind, isManifest, keyOf, nextSeq, orderFiles,
} from './files'
import type { Rejection, UploadedFile } from './files'
import s from './Upload.module.css'

/* Figma 7NlXeHdubRDwYnkxyXotvO — 113:2 "Bumpin - Upload Files" (empty) and
   113:43 "Bumpin - Files Uploaded" (populated). One route, one dashed surface,
   two contents; the state is simply whether any file is present.

   Each file is sent to POST /api/uploads as it lands. An equipment list becomes
   rows on the Equipment screen and the rider checks re-run against it; anything
   else is kept as Bumpin's memory, which the AI reads when it explains a finding
   or words a reply. The card shows which happened. */

interface State {
  files: UploadedFile[]
  rejections: Rejection[]
}

const EMPTY: State = { files: [], rejections: [] }

/* The list survives navigation.
 *
 * There is no upload endpoint — the screen holds what was dropped and nothing
 * leaves the browser — so without this the grid emptied the moment you left
 * the page and came back, and a file you had just "uploaded" was gone. Only
 * the card's own fields are kept; the File objects are not, because nothing
 * reads their bytes. Rejections are deliberately not kept: a warning about a
 * file you tried to add five minutes ago is noise on a fresh visit. */
const STORE_KEY = 'bumpin.uploaded-files.v1'

function restore(): State {
  try {
    const raw = window.localStorage.getItem(STORE_KEY)
    if (!raw) return EMPTY
    const files = JSON.parse(raw)
    if (!Array.isArray(files)) return EMPTY
    /* Anything that is not a card we wrote is dropped rather than rendered:
       the key is public and a half-written value must not break the screen. */
    return {
      files: files.filter((f): f is UploadedFile =>
        f && typeof f.id === 'string' && typeof f.name === 'string'
        && typeof f.size === 'number' && typeof f.seq === 'number')
        .map((f) => (f.status === 'reading' ? { ...f, status: 'failed' as const } : f)),
      rejections: [],
    }
  } catch {
    return EMPTY
  }
}

export function Upload() {
  const [{ files, rejections }, setState] = useState<State>(restore)

  useEffect(() => {
    try { window.localStorage.setItem(STORE_KEY, JSON.stringify(files)) } catch { /* private mode */ }
  }, [files])
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  /* dragenter/dragleave fire again every time the pointer crosses a child
     element, so a plain boolean flickers off the moment the cursor passes over
     a file card. Counting enters and leaves keeps the highlight on until the
     pointer genuinely leaves the zone. */
  const dragDepth = useRef(0)

  /* The latest list, for ingest to read without waiting on a state update. */
  const filesRef = useRef(files)
  filesRef.current = files

  const patch = useCallback((id: string, change: Partial<UploadedFile>) => {
    setState((prev) => ({ ...prev, files: prev.files.map((f) => (f.id === id ? { ...f, ...change } : f)) }))
  }, [])

  const ingest = useCallback((list: FileList | null) => {
    if (!list || list.length === 0) return
    const incoming = Array.from(list)
    const { added, rejected } = acceptFiles(incoming, filesRef.current, nextSeq(filesRef.current))
    const cards = added.map((c) => ({ ...c, status: 'reading' as const }))
    setState((prev) => ({
      files: cards.length ? [...prev.files, ...cards] : prev.files,
      rejections: rejected,
    }))
    /* One at a time, equipment lists first, so the riders are re-checked against
       the new equipment before anything that depends on it. */
    const byKey = new Map(incoming.map((f) => [keyOf(f), f]))
    const queue = [...cards].sort((a, b) => Number(isManifest(b)) - Number(isManifest(a)))
    void (async () => {
      for (const card of queue) {
        const file = byKey.get(card.key)
        if (!file) continue
        try {
          const [result] = await api.uploadFiles([file])
          patch(card.id, {
            status: result.stored_as === 'failed' ? 'failed' : 'done',
            result,
            docType: docTypeOfKind(result.kind, card.docType),
          })
        } catch {
          patch(card.id, { status: 'failed' })
        }
      }
    })()
  }, [patch])

  const removeFile = useCallback((id: string) => {
    setState((prev) => ({ ...prev, files: prev.files.filter((f) => f.id !== id) }))
  }, [])

  const dismissRejections = useCallback(() => {
    setState((prev) => (prev.rejections.length ? { ...prev, rejections: [] } : prev))
  }, [])

  const openPicker = useCallback(() => inputRef.current?.click(), [])

  const onInputChange = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    ingest(e.target.files)
    // Without this the input keeps its value, and picking the very same file a
    // second time fires no change event at all.
    e.target.value = ''
  }, [ingest])

  /* The whole screen takes the drop, not just the dashed rectangle.
     Two reasons. A file dropped anywhere else makes the browser navigate to
     it, which blows the SPA away. And aiming at the rectangle is a skill the
     operator should not need: dropping an inch wide of it used to be
     swallowed silently, so the file simply never arrived and nothing said
     why. Ingesting here means the drop lands wherever it is let go.
     The zone's own `onDrop` therefore does NOT ingest — one path only, or the
     same file arrives twice and the second copy is rejected as a duplicate. */
  useEffect(() => {
    const over = (e: globalThis.DragEvent) => e.preventDefault()
    const drop = (e: globalThis.DragEvent) => {
      e.preventDefault()
      dragDepth.current = 0
      setDragging(false)
      ingest(e.dataTransfer?.files ?? null)
    }
    window.addEventListener('dragover', over)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragover', over)
      window.removeEventListener('drop', drop)
    }
  }, [ingest])

  const carriesFiles = (e: DragEvent<HTMLDivElement>) =>
    Array.from(e.dataTransfer.types ?? []).includes('Files')

  const handlers = {
    onDragEnter: (e: DragEvent<HTMLDivElement>) => {
      if (!carriesFiles(e)) return
      e.preventDefault()
      dragDepth.current += 1
      setDragging(true)
    },
    onDragOver: (e: DragEvent<HTMLDivElement>) => {
      if (!carriesFiles(e)) return
      // Without preventDefault on dragover the drop event never fires.
      e.preventDefault()
      e.dataTransfer.dropEffect = 'copy'
    },
    onDragLeave: (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      dragDepth.current = Math.max(0, dragDepth.current - 1)
      if (dragDepth.current === 0) setDragging(false)
    },
    /* Only clears the highlight. The window listener above does the
       ingesting, so a drop on the zone and a drop beside it take one path. */
    onDrop: () => {
      dragDepth.current = 0
      setDragging(false)
    },
  }

  const ordered = orderFiles(files)

  return (
    <div className={s.screen}>
      {/* Nothing on this screen is a list, so there is nothing to narrow. */}
      <TopBar title="Upload venue files" searchable={false} />

      <input
        ref={inputRef}
        id="upload-file-input"
        className={s.srInput}
        type="file"
        multiple
        accept={ACCEPT_ATTR}
        onChange={onInputChange}
      />

      {files.length === 0 ? (
        <div className={s.emptyWrap}>
          <DropZone variant="empty" dragging={dragging} handlers={handlers} onPick={openPicker}>
            <span className={s.zoneIcon} aria-hidden>
              <UploadGlyph />
            </span>
            <div className={s.copy}>
              <p className={s.zoneTitle}>Upload files</p>
              <p className={s.instruction}>
                Drag and drop your files here, or{' '}
                <button
                  type="button"
                  className={s.selectLink}
                  onClick={(e) => { e.stopPropagation(); openPicker() }}
                >
                  click to select.
                </button>
              </p>
              <p className={s.formats}>
                {SUPPORTED_FORMATS} · up to 25 MB per file
              </p>
            </div>
          </DropZone>
        </div>
      ) : (
        <div className={s.overview}>
          <div className={s.filesHeader}>
            <h2 className={`${s.filesTitle} t-heading-sm`}>Uploaded files</h2>
            <span className={`${s.count} t-label-sm`}>{files.length}</span>
          </div>

          <DropZone variant="grid" dragging={dragging} handlers={handlers} onPick={openPicker}>
            <div className={s.grid}>
              {ordered.map((f) => (
                <FileCard key={f.id} file={f} onRemove={removeFile} />
              ))}
            </div>
          </DropZone>
        </div>
      )}

      {rejections.length > 0 && (
        <div className={s.rejects} role="status">
          {rejections.map((r, i) => (
            <span key={`${r.name}-${r.reason}-${i}`} className={`${s.reject} t-body-sm`}>
              <Chip tone="pink">{r.reason}</Chip>
              {r.name}
            </span>
          ))}
          <Button variant="quiet" size="sm" onClick={dismissRejections}>Dismiss</Button>
        </div>
      )}
    </div>
  )
}
