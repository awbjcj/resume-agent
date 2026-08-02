/** Shared sizing for the full-page chat surfaces (Scout, Coach, Interview).
 *
 * Declared once because the three pages had drifted to three unrelated values --
 * a fixed `36rem`, `min(70vh,52rem)`, and `min(62vh,46rem)` -- so the same
 * conversation UI was a different size on every page and the fixed one ignored
 * the viewport entirely, wasting most of a large screen.
 *
 * Viewport-relative with a rem ceiling: the surface grows with the display
 * instead of staying letterbox-sized, while the ceiling stops it becoming an
 * unreadable column on a very tall monitor. The floor keeps it usable on short
 * laptop screens, where `vh` alone would collapse the thread.
 */
export const CHAT_SURFACE_HEIGHT = "h-[min(76vh,60rem)] min-h-[30rem]";

/** Page container width for the chat surfaces, matching the app shell's own cap. */
export const CHAT_PAGE_WIDTH = "mx-auto w-full max-w-[1680px]";
