/* Pure helpers for the upload slice. No React, no network — everything here is
   a function of the browser's File object, so it can be reasoned about and
   checked in isolation.

   There is no upload endpoint on the backend (the only ingest path is
   POST /api/inbox/receive, which takes repo-relative paths that must already
   exist on disk, never bytes). So this screen holds its files in component
   state and derives every label below in the browser. */

/** The badge on the card: the file's own extension, uppercased. It used to be
 *  a closed union of the three spreadsheet formats the design's line
 *  advertised, and anything else was turned away at the door. Ravi's intake is
 *  whatever people actually send him — PDFs, scans, photographs of a
 *  handwritten page — so the screen takes any file and names it rather than
 *  deciding in advance which ones count. */
export type FileFormat = string

/** The three document types in the design (113:89, 113:99, 113:109), plus a
 *  fourth for anything the filename does not place. Guessing one of the three
 *  for an unrecognised file would hide the fact that nothing classified it. */
export type DocType =
  | 'Rider documents'
  | 'Vendor documents'
  | 'Equipment lists'
  /* The three files that set the festival up before any mail arrives: what the
     event is, the rules it is judged against, and what the venue owns. Without
     these two the brief landed in 'Unsorted documents' and the hospitality
     policy was read as a rider, which is the opposite of the point — the screen
     is supposed to show that Bumpin knows what each file is. */
  | 'Festival brief'
  | 'Policies and rules'
  | 'Unsorted documents'

export interface UploadedFile {
  id: string
  /** name|size|lastModified — identity for the "same file twice" check. */
  key: string
  /** Monotonic within a session. Display order and tie-break, not identity. */
  seq: number
  name: string
  size: number
  format: FileFormat
  docType: DocType
  uploadedAt: number
}

/* No 'Unsupported format'. Size and duplication are the only two reasons a
   file is turned away now. */
export type RejectReason = 'Over 25 MB' | 'Already added'

export interface Rejection {
  name: string
  reason: RejectReason
}

export const SUPPORTED_FORMATS = 'Any file type'
export const MAX_BYTES = 25 * 1024 * 1024

/** No filter on the native picker either, or the dialog would grey out the
 *  very files the drop zone now accepts. */
export const ACCEPT_ATTR = '*/*'

/** Lowercase extension without the dot. '' when the name has no extension,
 *  which is what a dropped folder looks like. */
export function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  if (dot <= 0 || dot === name.length - 1) return ''
  return name.slice(dot + 1).toLowerCase()
}

/** 'rider.pdf' -> 'PDF'. A name with no extension — which is what a dropped
 *  folder looks like — reads 'FILE' rather than an empty badge. */
export function formatOf(name: string): FileFormat {
  return extensionOf(name).toUpperCase() || 'FILE'
}

/* Order matters. "stage_equipment_manifest.csv" must land on Equipment lists
   before anything else looks at it, and "main_stage_av_checklist.csv" must not
   be pulled into Equipment lists by the bare word "stage" — which is why the
   equipment test asks for equipment/manifest/inventory, never "stage". */
export function docTypeOf(name: string): DocType {
  const n = name.toLowerCase()
  if (/brief|site[\s_-]?plan|festival[\s_-]?(description|overview)/.test(n)) return 'Festival brief'
  /* Before the rider and vendor tests on purpose: "hospitality_policy" is a
     rule, not a rider, and "vendor_requirements" is a rule, not a vendor's
     document. Both would otherwise be caught by the bare words below. */
  if (/polic(y|ies)|rules|requirements|eligibility|allowance/.test(n)) return 'Policies and rules'
  if (/equipment|manifest|inventory|backline|patch[\s_-]?list/.test(n)) return 'Equipment lists'
  if (/vendor|insurance|certificate|contract|catering|permit|licen[cs]e/.test(n)) return 'Vendor documents'
  if (/rider|hospitality|checklist|technical|\bav\b|[\s_-]av[\s_-]/.test(n)) return 'Rider documents'
  return 'Unsorted documents'
}

/** "42 KB" / "203 KB" / "1.4 MB" — matches the design's 113:89 meta line. */
export function formatSize(bytes: number): string {
  const kb = bytes / 1024
  if (kb < 1) return '<1 KB'
  if (kb < 1024) return `${Math.round(kb)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}

/** "12 Oct 2026" / "9 Oct 2026" — matches 113:90 and 113:140 (no leading zero). */
export function formatDate(ts: number): string {
  return new Date(ts).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

export const keyOf = (f: File) => `${f.name}|${f.size}|${f.lastModified}`

/** Pure. `seqBase` is passed in rather than read from a module counter so the
 *  whole thing can run inside a setState updater, which React may invoke twice. */
export function acceptFiles(
  incoming: File[],
  existing: UploadedFile[],
  seqBase: number,
  now: number = Date.now(),
): { added: UploadedFile[]; rejected: Rejection[] } {
  const added: UploadedFile[] = []
  const rejected: Rejection[] = []
  const seen = new Set(existing.map((f) => f.key))
  let seq = seqBase

  for (const file of incoming) {
    const format = formatOf(file.name)
    if (file.size > MAX_BYTES) {
      rejected.push({ name: file.name, reason: 'Over 25 MB' })
      continue
    }
    const key = keyOf(file)
    // Covers both "already on screen" and "the same file twice in one drop".
    if (seen.has(key)) {
      rejected.push({ name: file.name, reason: 'Already added' })
      continue
    }
    seen.add(key)
    added.push({
      id: `upload-${seq}`,
      key,
      seq,
      name: file.name,
      size: file.size,
      format,
      docType: docTypeOf(file.name),
      uploadedAt: now,
    })
    seq += 1
  }

  return { added, rejected }
}

export const nextSeq = (files: UploadedFile[]) =>
  files.reduce((max, f) => Math.max(max, f.seq), 0) + 1

/* ---- the ordering constraint -------------------------------------------- */

/* backend/app/artists/checks.py reads the whole inventory_items table before it
   can find a shortage, and check_double_booking JOINs inventory_items outright.
   With no manifest loaded, double-booking silently returns nothing and every
   rider line falls through to a low_confidence warning instead of a conflict.
   So the manifest is the baseline, and riders that arrive before it are held
   rather than checked against an empty table. */

export const isManifest = (f: UploadedFile) => f.docType === 'Equipment lists'
export const isRider = (f: UploadedFile) => f.docType === 'Rider documents'

export const hasManifest = (files: UploadedFile[]) => files.some(isManifest)

/** Rider files that cannot be checked yet because no manifest has landed. */
export const heldRiders = (files: UploadedFile[]) =>
  hasManifest(files) ? [] : files.filter(isRider)

/** Manifest first — it is the thing the screen asks for — then newest first. */
export function orderFiles(files: UploadedFile[]): UploadedFile[] {
  return [...files].sort((a, b) => {
    const am = isManifest(a) ? 0 : 1
    const bm = isManifest(b) ? 0 : 1
    if (am !== bm) return am - bm
    return b.seq - a.seq
  })
}
