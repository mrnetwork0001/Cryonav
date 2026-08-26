import { useEffect, type RefObject } from "react";

/**
 * Close a transient overlay when the user indicates they are done with it.
 *
 * A dropdown that only closes via its own toggle is a trap on a phone: the obvious gesture is
 * to tap the page, and when nothing happens the menu sits over the content until the user
 * hunts for the button again.
 *
 * Three deliberate details:
 *
 * POINTERDOWN, not click. On touch, `click` fires after a ~300 ms delay and after scrolling
 * has already begun, so a menu dismissed on `click` visibly lags the tap. `pointerdown` also
 * covers mouse, pen and touch in one listener.
 *
 * ESCAPE closes it too, because a dropdown that traps keyboard users is worse than one that
 * traps touch users - they have no gesture to fall back on.
 *
 * The listener is only attached WHILE OPEN. Leaving a document-level handler bound for the
 * lifetime of the page means every tap anywhere on the site runs it.
 */
export function useDismiss(
  ref: RefObject<HTMLElement | null>,
  open: boolean,
  close: () => void,
): void {
  useEffect(() => {
    if (!open) return;

    const onPointerDown = (e: PointerEvent) => {
      const el = ref.current;
      // A tap inside the overlay - including on the toggle that owns it - is not a dismissal.
      // Without this the toggle would close and immediately reopen, so it would never open.
      if (el && e.target instanceof Node && el.contains(e.target)) return;
      close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [ref, open, close]);
}
