import { useEffect, useRef } from 'react'

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'iframe',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function useDialogAccessibility<T extends HTMLElement>(
  open: boolean,
  onRequestClose: () => void,
  closeBlocked = false,
) {
  const dialogRef = useRef<T>(null)
  const closeRef = useRef(onRequestClose)
  const blockedRef = useRef(closeBlocked)

  useEffect(() => {
    closeRef.current = onRequestClose
  }, [onRequestClose])

  useEffect(() => {
    blockedRef.current = closeBlocked
  }, [closeBlocked])

  useEffect(() => {
    if (!open) return
    const dialog = dialogRef.current
    if (!dialog) return
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const focusable = () => [...dialog.querySelectorAll<HTMLElement>(focusableSelector)]
      .filter((element) => element.getClientRects().length > 0)
    const frame = window.requestAnimationFrame(() => focusable()[0]?.focus())

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        if (!blockedRef.current) closeRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const elements = focusable()
      if (!elements.length) {
        event.preventDefault()
        return
      }
      const first = elements[0]
      const last = elements.at(-1)
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first?.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      window.cancelAnimationFrame(frame)
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
      previousFocus?.focus()
    }
  }, [open])

  return dialogRef
}
