# 001 — Make agent activity legible

- **Status**: DONE
- **Commit**: c07f67b3
- **Severity**: HIGH
- **Category**: Cohesion, state indication, accessibility
- **Estimated scope**: 8 files, medium

## Problem

The app already has an AG-UI-like event contract (`text`, `reasoning`, tool
lifecycle, notices, settled/completed/failed), but the visual treatment does not
clearly distinguish conversation from agent activity. The assistant identity is
also always the generic “Bot”, so Coach, Interviewer, and Scout lose personality.

`web/src/components/chat/ChatMessage.tsx:44` currently treats every assistant as
the same undifferentiated bubble:

```tsx
<div className={cn("flex items-start gap-2 sm:gap-3", !assistant && "flex-row-reverse")}>
  <div className="mt-1 shrink-0 rounded-full border bg-background p-1.5 shadow-sm">
    {assistant ? <Bot className="size-4" /> : <UserRound className="size-4" />}
  </div>
```

`web/src/components/chat/parts/ReasoningPart.tsx:15` conditionally unmounts the
Base UI panel, so it cannot play an interruptible exit transition:

```tsx
{open ? (
  <CollapsibleContent className="mt-1 whitespace-pre-wrap rounded-md bg-muted/60 p-2 text-xs text-muted-foreground">
    {text}
  </CollapsibleContent>
) : null}
```

`web/src/components/chat/parts/ToolPart.tsx:15` and `:26` present a tool call as a
plain pill whose detail snaps open:

```tsx
<CollapsibleTrigger className="flex max-w-full items-center gap-2 rounded-full border bg-background/70 px-2.5 py-1 text-xs text-muted-foreground">
...
<CollapsibleContent className="mt-1 whitespace-pre-wrap rounded-md bg-muted/60 p-2 text-xs text-muted-foreground">
```

## Target

Create a crisp, structured agent-message system inspired by AG-UI's separation
of real-time chat, tool activity, structured messages, and human collaboration.
Do not change `web/src/lib/chat/events.ts` or the backend stream.

1. Extend `ChatThread`/`ChatMessage` with `assistantName` and `assistantIcon`
   presentation props. Defaults remain `Assistant` and `Bot`; pages can pass
   `Profile coach`, `Interviewer`, or `Discovery Scout` plus an icon.
2. Add a small assistant label above assistant content. Do not add a label to
   every user message.
3. Style tool and reasoning parts as a quiet “Agent activity” stack inside the
   assistant message: compact status icon, human-readable action name, summary,
   and disclosure. Preserve raw previews inside the disclosure.
4. Give tool completion an `aria-live="polite"` status. Never announce streaming
   text token-by-token.
5. Keep chat messages static. No slide-in, stagger, or bubble bounce.

Use this exact disclosure motion on Base UI panels:

```tsx
className={cn(
  "mt-1 overflow-hidden rounded-lg bg-muted/55 p-2 text-xs text-muted-foreground",
  "translate-y-0 opacity-100 transition-[opacity,transform] duration-[160ms] ease-out-strong",
  "data-starting-style:-translate-y-1 data-starting-style:opacity-0",
  "data-ending-style:-translate-y-1 data-ending-style:opacity-0",
  "motion-reduce:translate-y-0 motion-reduce:transition-opacity",
)}
```

Use this exact state-transition treatment on an activity trigger:

```tsx
className="group/activity flex max-w-full items-center gap-2 rounded-lg border bg-muted/35 px-2.5 py-1.5 text-xs text-muted-foreground transition-[background-color,border-color,color] duration-[160ms] ease-out-strong hover:bg-muted/60"
```

Hover changes color only. Do not move or scale the activity row. The existing
button primitive already supplies `scale(0.98)` press feedback to actual buttons.

Add a reusable artifact entrance class to `web/src/index.css` for rare, discrete
agent outputs (Coach draft notes and Interview debriefs only):

```css
.agent-artifact-enter {
  opacity: 1;
  transform: translateY(0);
  transition:
    opacity 180ms var(--ease-out-strong),
    transform 180ms var(--ease-out-strong);
}
@starting-style {
  .agent-artifact-enter {
    opacity: 0;
    transform: translateY(6px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .agent-artifact-enter {
    transform: none;
    transition: opacity 160ms var(--ease-out-strong);
  }
  @starting-style {
    .agent-artifact-enter { opacity: 0; }
  }
}
```

## Repo conventions to follow

- Strong curves already live at `web/src/index.css:61-62` as
  `--ease-out-strong` and `--ease-in-out-strong`.
- Press feedback already lives in `web/src/components/ui/button.tsx:7`; do not
  duplicate it in chat components.
- Base UI 1.6 panels expose `data-starting-style` and `data-ending-style`; keep
  panels mounted so transitions can reverse cleanly.
- The stream reducer at `web/src/lib/chat/events.ts:92-135` is the source of
  truth. Presentation changes must not reinterpret or reorder events.

## Steps

1. Add `assistantName` and `assistantIcon` props to `ChatThread`, pass them to
   `ChatMessage`, and keep backward-compatible defaults.
2. Refactor `ChatMessage` to render a small assistant identity line and improve
   spacing/contrast while preserving part order and memoization correctness.
3. Restyle `ToolPart`; expose pending/success/failure as text plus icon, add a
   polite live region, and apply the exact interruptible panel transition above.
4. Keep `ReasoningPart`'s panel mounted, rename the trigger to “Working notes”,
   and apply the same panel transition. Retain controlled open state.
5. Refine `NoticePart` as an inline event notice with the same border radius and
   spacing system; no motion.
6. Add `.agent-artifact-enter` to `web/src/index.css` exactly as specified.
7. Add `web/src/components/chat/ChatMessage.test.tsx` covering assistant label,
   tool pending/completed/failed status, reasoning disclosure, and user-message
   rendering. Extend `ChatThread.test.tsx` for prop forwarding.

## Boundaries

- Do NOT add an AG-UI package or change the SSE schema.
- Do NOT expose hidden chain-of-thought. Only render the existing `reasoning`
  text already authorized by the current product contract.
- Do NOT animate message arrival, streaming tokens, scroll-to-bottom, or
  keyboard submission.
- Do NOT change Coach/Interview/Scout page layouts in this plan.

## Verification

- **Mechanical**: from `web/`, run `npm run test:run -- src/components/chat`,
  `npm run lint`, and `npm run build`; all must pass.
- **Feel check**: stream a response containing text, one tool call, reasoning,
  and a notice. Confirm text remains primary, activity is scannable, and raw
  detail is one click away. Spam the disclosure and confirm it reverses without
  restarting. At 10% DevTools playback, confirm only opacity and a 4px upward
  offset move. With reduced motion, confirm the offset disappears but the fade
  remains.
- **Done when**: every stream part has a distinct accessible role, assistant
  identity can be page-specific, and no event or message ordering changed.
