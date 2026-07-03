# Filter and Pipeline UI Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a status-first filter command desk with polished fit and salary thresholds, exclusive facet popovers, and post-processed-first collapsible pipeline groups.

**Architecture:** Keep applied filter data in the existing `FilterState`/URL flow and add only ephemeral UI state for the active facet and expanded pipeline groups. Upgrade the local popover wrapper to the installed Base UI primitive, keep scalar edits draft-based until Apply, and extract pipeline stage rendering into a focused component.

**Tech Stack:** React 19, TypeScript 6, Vite 8, Tailwind CSS 4, shadcn/ui base-nova, Base UI, Vitest, Testing Library, MSW.

---

## File map

- Modify `web/src/components/ui/popover.tsx`: expose the official Base UI-backed controlled popover API and semantic header primitives.
- Modify `web/src/components/filters/FacetPopover.tsx`: controlled open state, refined header/list/footer, Clear and Done actions.
- Modify `web/src/components/filters/FacetPopover.test.tsx`: verify controlled presentation and actions.
- Modify `web/src/components/FilterDesk.tsx`: own the single active facet and render Status first.
- Modify `web/src/components/FilterDesk.test.tsx`: verify control order, exclusive overlays, and salary behavior.
- Modify `web/src/components/FilterDesk.fitslider.test.tsx`: verify the composed numeric/slider fit threshold.
- Modify `web/src/components/MinFitInput.tsx`: pair exact numeric entry with a controlled shadcn Slider.
- Create `web/src/components/SalaryThresholdInput.tsx`: isolate currency parsing, validation copy, and compact annual summary.
- Create `web/src/features/pipeline/pipeline-stages.ts`: centralize stable stage ordering, labels, and default-open state.
- Create `web/src/features/pipeline/PipelineStageSection.tsx`: render one accessible collapsible stage group.
- Modify `web/src/features/pipeline/PipelineContainer.tsx`: reorder filter fields and control expanded stage state.
- Modify `web/src/features/pipeline/PipelineContainer.test.tsx`: verify ordering, initial expansion, and independent hiding.

### Task 1: Controlled, polished facet popovers

**Files:**

- Modify: `web/src/components/ui/popover.tsx`
- Modify: `web/src/components/filters/FacetPopover.tsx`
- Test: `web/src/components/filters/FacetPopover.test.tsx`

- [ ] **Step 1: Write failing controlled-popover and action tests**

Extend `FacetPopover.test.tsx` with explicit controlled props and these assertions:

```tsx
it("renders a labeled panel with selection actions", () => {
  const onChange = vi.fn();
  const onOpenChange = vi.fn();

  render(
    <FacetPopover
      label="Skills"
      counts={{ python: 52, react: 38 }}
      selected={new Set(["python"])}
      onChange={onChange}
      open
      onOpenChange={onOpenChange}
    />,
  );

  expect(screen.getByText("Filter by Skills")).toBeInTheDocument();
  expect(screen.getByText("1 selected")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Clear Skills filter" }));
  expect(onChange).toHaveBeenCalledWith(new Set());

  fireEvent.click(
    screen.getByRole("button", { name: "Done filtering Skills" }),
  );
  expect(onOpenChange).toHaveBeenCalledWith(false);
});

it("reports an empty search without losing the footer actions", () => {
  render(
    <FacetPopover
      label="Skills"
      counts={{ python: 52 }}
      selected={new Set()}
      onChange={vi.fn()}
      open
      onOpenChange={vi.fn()}
    />,
  );

  fireEvent.change(screen.getByPlaceholderText("Search skills..."), {
    target: { value: "rust" },
  });

  expect(screen.getByText("No matching skills")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Done filtering Skills" }),
  ).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```bash
cd web
npm run test:run -- src/components/filters/FacetPopover.test.tsx
```

Expected: FAIL because `FacetPopover` does not accept `open`/`onOpenChange` and does not render the new panel actions.

- [ ] **Step 3: Upgrade the local popover wrapper without overwriting consumer code**

Replace the custom context implementation in `ui/popover.tsx` with the current Base UI composition already present in `@base-ui/react`. Preserve the exported names used by `NotificationsBell` and add the semantic exports needed by facets:

```tsx
import * as React from "react";
import { Popover as PopoverPrimitive } from "@base-ui/react/popover";

import { cn } from "@/lib/utils";

function Popover(props: PopoverPrimitive.Root.Props) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />;
}

function PopoverTrigger(props: PopoverPrimitive.Trigger.Props) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />;
}

function PopoverContent({
  className,
  align = "center",
  alignOffset = 0,
  side = "bottom",
  sideOffset = 4,
  ...props
}: PopoverPrimitive.Popup.Props &
  Pick<
    PopoverPrimitive.Positioner.Props,
    "align" | "alignOffset" | "side" | "sideOffset"
  >) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Positioner
        align={align}
        alignOffset={alignOffset}
        side={side}
        sideOffset={sideOffset}
        className="isolate z-50"
      >
        <PopoverPrimitive.Popup
          data-slot="popover-content"
          className={cn(
            "z-50 flex w-72 origin-(--transform-origin) flex-col gap-2.5 rounded-lg bg-popover p-2.5 text-sm text-popover-foreground shadow-md ring-1 ring-foreground/10 outline-hidden duration-100 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
            className,
          )}
          {...props}
        />
      </PopoverPrimitive.Positioner>
    </PopoverPrimitive.Portal>
  );
}

function PopoverHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="popover-header"
      className={cn("flex flex-col gap-0.5", className)}
      {...props}
    />
  );
}

function PopoverTitle({ className, ...props }: PopoverPrimitive.Title.Props) {
  return (
    <PopoverPrimitive.Title
      data-slot="popover-title"
      className={cn("font-medium", className)}
      {...props}
    />
  );
}

function PopoverDescription({
  className,
  ...props
}: PopoverPrimitive.Description.Props) {
  return (
    <PopoverPrimitive.Description
      data-slot="popover-description"
      className={cn("text-muted-foreground", className)}
      {...props}
    />
  );
}

export {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
};
```

This is a manual smart merge of the inspected `npx shadcn@latest add popover --diff popover.tsx`; do not run `--overwrite`.

- [ ] **Step 4: Implement the controlled facet panel**

Add props to `FacetPopover`:

```tsx
open: boolean
onOpenChange: (open: boolean) => void
presentation?: "chip" | "field"
```

Use `<Popover open={open} onOpenChange={onOpenChange}>`. Compose the content as:

```tsx
<PopoverContent
  align="start"
  className="w-[min(20rem,calc(100vw-2rem))] gap-0 p-0"
>
  <PopoverHeader className="border-b p-3">
    <div className="flex items-center justify-between gap-3">
      <PopoverTitle>Filter by {label}</PopoverTitle>
      <Badge variant="secondary">{selected.size} selected</Badge>
    </div>
    <PopoverDescription>
      Select any values that should remain visible.
    </PopoverDescription>
  </PopoverHeader>
  <Command>
    <CommandInput
      placeholder={`Search ${label.toLowerCase()}...`}
      value={q}
      onValueChange={setQ}
    />
    <CommandList className="max-h-64">
      {shown.length === 0 && (
        <CommandEmpty>No matching {label.toLowerCase()}</CommandEmpty>
      )}
      <CommandGroup className="flex flex-col gap-1">
        {shown.map((option) => {
          const checked = selected.has(option);
          return (
            <CommandItem
              key={option}
              value={option}
              onSelect={() => toggle(option)}
            >
              <Checkbox checked={checked} aria-hidden />
              <span className="flex-1 truncate">
                {getLabel ? getLabel(option) : option}
              </span>
              <span className="text-xs tabular-nums text-muted-foreground">
                {counts[option]}
              </span>
              {checked && <CheckIcon className="text-primary" />}
            </CommandItem>
          );
        })}
      </CommandGroup>
    </CommandList>
  </Command>
  <div className="flex items-center justify-between gap-2 border-t p-2">
    <Button
      type="button"
      variant="ghost"
      size="sm"
      aria-label={`Clear ${label} filter`}
      disabled={selected.size === 0}
      onClick={() => onChange(new Set())}
    >
      Clear
    </Button>
    <Button
      type="button"
      size="sm"
      aria-label={`Done filtering ${label}`}
      onClick={() => onOpenChange(false)}
    >
      Done
    </Button>
  </div>
</PopoverContent>
```

For `presentation="field"`, use the existing outline Button with `className="h-10 w-full justify-between"`; for chips retain the compact rounded trigger. Reset the local search query when the panel closes.

- [ ] **Step 5: Run the test and commit**

Run the focused test; expected PASS. Then:

```bash
git add web/src/components/ui/popover.tsx web/src/components/filters/FacetPopover.tsx web/src/components/filters/FacetPopover.test.tsx
git commit -m "feat(web): refine controlled facet popovers"
```

### Task 2: Status-first command desk and polished thresholds

**Files:**

- Create: `web/src/components/SalaryThresholdInput.tsx`
- Modify: `web/src/components/MinFitInput.tsx`
- Modify: `web/src/components/FilterDesk.tsx`
- Test: `web/src/components/FilterDesk.test.tsx`
- Test: `web/src/components/FilterDesk.fitslider.test.tsx`

- [ ] **Step 1: Write failing hierarchy, exclusivity, and threshold tests**

Add status/source facet data and verify DOM order with `compareDocumentPosition`. Add this interaction test:

```tsx
it("keeps only one facet panel open", async () => {
  const user = userEvent.setup();
  render(
    <FilterDesk
      filter={emptyFilterState()}
      facets={{ status: { tailored: 2 }, source: { greenhouse: 1 } }}
      total={3}
      onChange={vi.fn()}
    />,
  );

  await user.click(screen.getByRole("button", { name: /^Status/ }));
  expect(screen.getByText("Filter by Status")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /^Source/ }));
  expect(screen.queryByText("Filter by Status")).not.toBeInTheDocument();
  expect(screen.getByText("Filter by Source")).toBeInTheDocument();
});
```

Replace the obsolete “numeric input instead of a slider” assertion with:

```tsx
expect(screen.getByRole("spinbutton", { name: "Min fit" })).toBeInTheDocument();
expect(
  screen.getByRole("slider", { name: "Minimum fit slider" }),
).toBeInTheDocument();
```

Extend the existing draft test to expect the annual salary summary after typing `120000`:

```tsx
expect(screen.getByText("$120k+ / year")).toBeInTheDocument();
```

- [ ] **Step 2: Run the two FilterDesk test files and verify failure**

```bash
cd web
npm run test:run -- src/components/FilterDesk.test.tsx src/components/FilterDesk.fitslider.test.tsx
```

Expected: FAIL because the slider, summary, ordering, and exclusive state do not exist.

- [ ] **Step 3: Compose the fit threshold**

Keep the existing clamping helper and add the installed Slider:

```tsx
<div className="flex items-center gap-2">
  <Input
    id={id}
    aria-label="Min fit"
    type="number"
    min={0}
    max={100}
    step={1}
    inputMode="numeric"
    placeholder="Any"
    className="w-24 tabular-nums"
    value={value === 0 ? "" : value}
    onChange={(event) => onChange(fitValue(event.target.value))}
  />
  <span className="text-sm tabular-nums text-muted-foreground">/ 100</span>
</div>
<Slider
  aria-label="Minimum fit slider"
  value={[value]}
  min={0}
  max={100}
  step={1}
  onValueChange={(values) => onChange(values[0] ?? 0)}
/>
```

- [ ] **Step 4: Create the salary threshold component**

Move salary presentation and validation out of `FilterDesk` while keeping the draft string controlled by the parent:

```tsx
export function salarySummary(value: string) {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount <= 0) return "Any annual salary";
  const compact = new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: amount >= 100_000 ? 0 : 1,
  }).format(amount);
  return `$${compact.toLowerCase()}+ / year`;
}

export function SalaryThresholdInput({
  id,
  value,
  valid,
  onChange,
}: {
  id: string;
  value: string;
  valid: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label
        htmlFor={id}
        className="text-xs font-semibold uppercase tracking-[0.14em]"
      >
        Min salary
      </Label>
      <div className="relative">
        <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-muted-foreground">
          $
        </span>
        <Input
          id={id}
          type="number"
          min={0}
          step={10_000}
          inputMode="numeric"
          className="pl-7 tabular-nums"
          value={value}
          aria-invalid={valid ? undefined : true}
          aria-describedby={`${id}-hint`}
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
      <p
        id={`${id}-hint`}
        className={
          valid ? "text-xs text-muted-foreground" : "text-xs text-destructive"
        }
      >
        {valid ? salarySummary(value) : "Enter a non-negative annual salary."}
      </p>
    </div>
  );
}
```

- [ ] **Step 5: Recompose `FilterDesk`**

Add `const [openFacet, setOpenFacet] = useState<FacetSpec["key"] | null>(null)`. Remove Status from the secondary `facetSpecs`, render its `FacetPopover` first in the primary responsive grid with `presentation="field"`, then Min fit, Min salary, Sort, Search, and conditional Preset. Pass every secondary facet:

```tsx
open={openFacet === key}
onOpenChange={(open) => setOpenFacet(open ? key : null)}
```

Use `SalaryThresholdInput` with `salaryDraft.valid`. Preserve `applyPrimaryFilters`, `removeFilter`, `clearFilters`, sort/preset behavior, and URL-facing `FilterState` values exactly.

- [ ] **Step 6: Run tests and commit**

Run both FilterDesk files; expected PASS. Then:

```bash
git add web/src/components/FilterDesk.tsx web/src/components/FilterDesk.test.tsx web/src/components/FilterDesk.fitslider.test.tsx web/src/components/MinFitInput.tsx web/src/components/SalaryThresholdInput.tsx
git commit -m "feat(web): build status-first filter command desk"
```

### Task 3: Post-processed-first collapsible pipeline groups

**Files:**

- Create: `web/src/features/pipeline/pipeline-stages.ts`
- Create: `web/src/features/pipeline/PipelineStageSection.tsx`
- Modify: `web/src/features/pipeline/PipelineContainer.tsx`
- Test: `web/src/features/pipeline/PipelineContainer.test.tsx`

- [ ] **Step 1: Write failing ordering and visibility tests**

Add this fixture helper, then return Tailored, Rendered, Approved, Raw, and unknown `screening` rows from the test server:

```tsx
const pipelineItem = (jobId: number, status: string, title: string) => ({
  jobId,
  company: `${status} Co`,
  title,
  status,
  fitScore: 80,
  jdText: `${status} description`,
  critiqueJson: null,
  pdfPath: null,
  applicationStatus: null,
  hasProgress: status === "tailored" || status === "rendered",
});

server.use(
  http.get("/api/pipeline", () =>
    HttpResponse.json({
      data: [
        pipelineItem(1, "raw", "Raw role"),
        pipelineItem(2, "approved", "Approved role"),
        pipelineItem(3, "rendered", "Rendered role"),
        pipelineItem(4, "tailored", "Tailored role"),
        pipelineItem(5, "screening", "Screening role"),
      ],
      pagination: { page: 1, pageSize: 200, totalItems: 5, totalPages: 1 },
      facets: {
        status: { raw: 1, approved: 1, rendered: 1, tailored: 1, screening: 1 },
      },
      total: 5,
    }),
  ),
);
```

Assert heading order is `Tailored, Rendered, Approved, Raw, Screening`; Tailored and Rendered job titles are initially visible; Approved, Raw, and Screening titles are initially absent. Then click the Approved trigger, assert its job appears, click again, and assert it is hidden.

Use role queries so the test verifies accessible controls:

```tsx
const tailored = screen.getByRole("button", { name: /tailored.*1 job/i });
const rendered = screen.getByRole("button", { name: /rendered.*1 job/i });
const approved = screen.getByRole("button", { name: /approved.*1 job/i });

expect(tailored).toHaveAttribute("aria-expanded", "true");
expect(rendered).toHaveAttribute("aria-expanded", "true");
expect(approved).toHaveAttribute("aria-expanded", "false");

await user.click(approved);
expect(screen.getByText("Approved role")).toBeInTheDocument();
await user.click(approved);
expect(screen.queryByText("Approved role")).not.toBeInTheDocument();
```

- [ ] **Step 2: Run the pipeline test and verify failure**

```bash
cd web
npm run test:run -- src/features/pipeline/PipelineContainer.test.tsx
```

Expected: FAIL because all groups are always visible and Rendered is ordered after Approved.

- [ ] **Step 3: Add stage metadata helpers**

Create `pipeline-stages.ts`:

```ts
export const PIPELINE_STAGE_ORDER = [
  "tailored",
  "rendered",
  "approved",
  "shortlisted",
  "raw",
  "rejected",
] as const;

const rank = new Map<string, number>(
  PIPELINE_STAGE_ORDER.map((stage, index) => [stage, index]),
);

export function orderPipelineStages(stages: Iterable<string>) {
  return [...stages].sort((left, right) => {
    const leftRank = rank.get(left) ?? Number.MAX_SAFE_INTEGER;
    const rightRank = rank.get(right) ?? Number.MAX_SAFE_INTEGER;
    return leftRank - rightRank || left.localeCompare(right);
  });
}

export function initialOpenPipelineStages() {
  return new Set<string>(["tailored", "rendered"]);
}

export function pipelineStageLabel(stage: string) {
  return stage
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
```

- [ ] **Step 4: Extract an accessible stage section**

Create `PipelineStageSection.tsx` using `Collapsible`, `CollapsibleTrigger`, and `CollapsibleContent`. Its props are:

```ts
type PipelineStageSectionProps = {
  stage: string;
  rows: PipelineItem[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  isSelected: (jobId: number) => boolean;
  onSelect: (row: PipelineItem) => void;
  onOpen: (row: PipelineItem) => void;
};
```

The trigger is a full-width Button-compatible control containing a level-two heading, pluralized count (`1 job`, `2 jobs`), and `ChevronDownIcon` with `data-icon="inline-end"` plus `transition-transform group-data-panel-open:rotate-180`. The content contains the existing responsive `PipelineCard` grid. Do not duplicate filter or selection state in this component.

- [ ] **Step 5: Control pipeline stage expansion and reorder filters**

In `PipelineContainer`:

```tsx
const [openStages, setOpenStages] = useState(initialOpenPipelineStages);
const stages = orderPipelineStages(byStage.keys());

const setStageOpen = (stage: string, open: boolean) => {
  setOpenStages((current) => {
    const next = new Set(current);
    if (open) next.add(stage);
    else next.delete(stage);
    return next;
  });
};
```

Render `PipelineStageSection` for each returned stage. Move the Status Select to the first cell in the filter form, Min fit second, Company/title third, and Apply last. Import `PIPELINE_STAGE_ORDER` for both status selects so display order and mutation choices agree.

- [ ] **Step 6: Run the pipeline tests and commit**

Run the focused test; expected PASS. Then:

```bash
git add web/src/features/pipeline/PipelineContainer.tsx web/src/features/pipeline/PipelineContainer.test.tsx web/src/features/pipeline/PipelineStageSection.tsx web/src/features/pipeline/pipeline-stages.ts
git commit -m "feat(web): add collapsible pipeline stage groups"
```

### Task 4: Regression, accessibility, and responsive verification

**Files:**

- Modify only if a verification failure requires a scoped fix.

- [ ] **Step 1: Run all directly affected tests**

```bash
cd web
npm run test:run -- src/components/filters/FacetPopover.test.tsx src/components/FilterDesk.test.tsx src/components/FilterDesk.fitslider.test.tsx src/features/pipeline/PipelineContainer.test.tsx
```

Expected: all tests PASS.

- [ ] **Step 2: Run the complete web checks**

```bash
cd web
npm run test:run
npm run build
npm run lint
```

Expected: Vitest exits 0, TypeScript/Vite build exits 0, ESLint exits 0.

- [ ] **Step 3: Verify responsive and keyboard behavior in a real browser**

Start the API and Vite app in separate terminals:

```bash
uv run resume-agent serve --host 127.0.0.1 --port 8000
npm --prefix web run dev -- --host 127.0.0.1 --port 5173
```

Then check Pipeline and Shortlist at 320, 768, 1024, and 1440 pixels. At each width verify:

- controls do not overflow;
- Status is encountered first;
- Tab/Enter/Escape operate facet popovers;
- opening Source closes Status;
- salary invalid copy is visible and Apply is disabled;
- Tailored and Rendered start open;
- every pipeline stage trigger can hide and restore its cards;
- there are no console or accessibility errors.

- [ ] **Step 4: Review the final diff and commit any verification fixes**

```bash
git diff --check
git status --short
```

If Step 3 required fixes, rerun the focused test, stage only the feature files, and commit them:

```bash
git add web/src/components/FilterDesk.tsx web/src/components/MinFitInput.tsx web/src/components/SalaryThresholdInput.tsx web/src/components/filters/FacetPopover.tsx web/src/components/ui/popover.tsx web/src/features/pipeline/PipelineContainer.tsx web/src/features/pipeline/PipelineStageSection.tsx web/src/features/pipeline/pipeline-stages.ts
git commit -m "fix(web): resolve filter and pipeline verification findings"
```
