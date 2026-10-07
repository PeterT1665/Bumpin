import type { DragEvent, ReactNode } from 'react'
import s from './Upload.module.css'

/** The 10/8 dash on 113:35 and 113:80 cannot be expressed with
 *  `border-style: dashed`, so the outline is a stroked SVG rect sitting on top
 *  of the element. Values read straight off the node:
 *    strokeWeight 1.5, strokeAlign INSIDE, dashPattern [10, 8],
 *    cornerRadius 24, stroke #b5ac99 (--ink-300).
 *  The rect is inset half a stroke by `.outline`, so rx is 24 - 0.75. */
function DashedOutline() {
  return (
    <svg className={s.outline} aria-hidden focusable="false">
      <rect
        x="0" y="0" width="100%" height="100%"
        rx="23.25" ry="23.25"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeDasharray="10 8"
      />
    </svg>
  )
}

export interface DragHandlers {
  onDragEnter: (e: DragEvent<HTMLDivElement>) => void
  onDragOver: (e: DragEvent<HTMLDivElement>) => void
  onDragLeave: (e: DragEvent<HTMLDivElement>) => void
  onDrop: (e: DragEvent<HTMLDivElement>) => void
}

/** One dashed surface, two contents. 113:35 holds the empty-state copy and
 *  113:80 holds the file grid, but they are the same fill, stroke, dash and
 *  radius — so files can be dropped on either. */
export function DropZone({ variant, dragging, handlers, onPick, children }: {
  variant: 'empty' | 'grid'
  dragging: boolean
  handlers: DragHandlers
  onPick: () => void
  children: ReactNode
}) {
  const classes = [
    s.zone,
    variant === 'empty' ? s.zone_empty : s.zone_grid,
    dragging ? s.zone_dragging : '',
  ].join(' ')

  return (
    <div
      className={classes}
      data-dragging={dragging || undefined}
      {...handlers}
      onClick={(e) => {
        // In the grid variant the cards and their buttons live inside the zone,
        // so only a click on the bare surface should open the picker. In the
        // empty variant the whole surface is the target, but the "click to
        // select" button stops its own click so the picker never opens twice.
        if (variant === 'grid' && e.target !== e.currentTarget) return
        onPick()
      }}
    >
      <DashedOutline />
      {children}
    </div>
  )
}

/** 113:37 "Upload glyph" — VECTOR 28 x 28, stroke #847244 (--surface-backdrop),
 *  strokeWeight 3, cap ROUND, join ROUND. The path data is copied verbatim.
 *  Figma's strokeAlign is CENTER, so the stroke overhangs the 28x28 path box by
 *  1.5 on each side; the viewBox is widened by 2 so nothing clips. */
export function UploadGlyph() {
  return (
    <svg
      width="32" height="32" viewBox="-2 -2 32 32"
      fill="none" aria-hidden focusable="false"
    >
      <path
        d="M 14 20 L 14 0 M 14 0 L 6 8 M 14 0 L 22 8 M 0 20 L 0 25 C 0 27 1 28 3 28 L 25 28 C 27 28 28 27 28 25 L 28 20"
        stroke="var(--surface-backdrop)"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
