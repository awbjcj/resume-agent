# Wizard + Settings Web (Phase 2 of dashboard/wizard/config) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Settings section that edits every config over the Phase-1 API, and a four-step first-run wizard (keys → documents → search → sources) that shares the same forms and finishes with a profile-build run.

**Architecture:** New `features/settings/` (layout + per-domain pages + shared form primitives) and `features/setup/` (wizard shell + steps + gate). Forms are shared components consumed by both surfaces; all data access goes through the generated `openapi-fetch` client (`@/lib/api/client`) with TanStack Query. Wizard steps commit per step; resume position derives from `GET /api/setup/status`.

**Tech Stack:** React 19, Vite, react-router-dom v7, TanStack Query v5, shadcn (base-ui flavor — `render=` prop, NOT `asChild`), Tailwind v4, vitest + Testing Library + MSW.

**Spec:** `docs/superpowers/specs/2026-07-01-dashboard-wizard-config-design.md`

## Global Constraints

- **Phase 1 (backend plan `2026-07-01-config-api-backend.md`) must be merged first**; `web/src/lib/api/schema.ts` must already contain the new routes.
- Web working dir is `web/`; commands: `npm run test:run`, `npm run lint`, `npm run build`.
- shadcn components live in `web/src/components/ui/` (base-ui primitive flavor: custom triggers use `render={<.../>}`, not `asChild`).
- Follow the shadcn rules: `FieldGroup`/`Field` for form layout, `flex gap-*` not `space-y-*`, semantic color tokens only, `Empty` for empty states, `sonner` for toasts, icons via `lucide-react`.
- All copy in sentence case, active voice, verbs on buttons say what happens ("Save changes", not "Submit").
- Every new page is lazy-loaded in `router.tsx` like the existing pages.
- `connectors.yaml` editing = the existing Sources feature; never call `/api/config` for sources.
- Secrets are write-only: never render a secret value; set keys show `••••` + hint.
- Tests colocate as `*.test.tsx` next to components, MSW for network, following `web/src/features/sources/use-sources.test.tsx` patterns (read it before writing the first test).

---

### Task 1: Settings shell — routes, layout, secondary nav, sidebar entry

**Files:**
- Create: `web/src/features/settings/SettingsLayout.tsx`
- Modify: `web/src/app/router.tsx`, `web/src/app/AppLayout.tsx`
- Test: `web/src/features/settings/SettingsLayout.test.tsx`

**Interfaces:**
- Produces: routes `/settings/*` rendering `SettingsLayout` (secondary nav + `<Outlet/>`); `SETTINGS_NAV` export: `{ to, label }[]` for `profile`, `search`, `sources`, `keys`, `review`, `rendering`, `pruning`, `style-guide`. Placeholder index redirect `/settings` → `/settings/profile`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/settings/SettingsLayout.test.tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { SettingsLayout, SETTINGS_NAV } from "./SettingsLayout";

describe("SettingsLayout", () => {
  it("renders one nav link per settings area", () => {
    render(
      <MemoryRouter initialEntries={["/settings/search"]}>
        <Routes>
          <Route path="/settings" element={<SettingsLayout />}>
            <Route path="search" element={<div>search page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    for (const item of SETTINGS_NAV) {
      expect(screen.getByRole("link", { name: item.label })).toBeInTheDocument();
    }
    expect(screen.getByText("search page")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/settings/SettingsLayout.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement layout + routing**

```tsx
// web/src/features/settings/SettingsLayout.tsx
import { NavLink, Outlet } from "react-router-dom";

import { cn } from "@/lib/utils";

export const SETTINGS_NAV = [
  { to: "/settings/profile", label: "Profile & documents" },
  { to: "/settings/search", label: "Search" },
  { to: "/settings/sources", label: "Sources" },
  { to: "/settings/keys", label: "API keys" },
  { to: "/settings/review", label: "Review panel" },
  { to: "/settings/rendering", label: "Rendering" },
  { to: "/settings/pruning", label: "Pruning" },
  { to: "/settings/style-guide", label: "Style guide" },
] as const;

export function SettingsLayout() {
  return (
    <div className="flex flex-col gap-6 lg:flex-row lg:gap-10">
      <nav aria-label="Settings" className="lg:w-56 lg:shrink-0">
        <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Settings
        </div>
        <ul className="mt-3 flex flex-row flex-wrap gap-1 lg:flex-col">
          {SETTINGS_NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    "block rounded-lg px-3 py-2 text-sm hover:bg-accent",
                    isActive && "bg-accent font-medium",
                  )
                }
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className="min-w-0 flex-1 max-w-3xl">
        <Outlet />
      </div>
    </div>
  );
}
```

In `web/src/app/router.tsx`, add a lazy import and a nested route block (pages
arrive in later tasks; register them as they land — for now only the layout +
index redirect):

```tsx
import { Navigate } from "react-router-dom";
const SettingsLayout = lazy(() =>
  import("@/features/settings/SettingsLayout").then((m) => ({ default: m.SettingsLayout })),
);
// inside children:
{
  path: "settings",
  element: page(<SettingsLayout />),
  children: [{ index: true, element: <Navigate to="/settings/profile" replace /> }],
},
```

In `web/src/app/AppLayout.tsx`, add a second sidebar group below "Workflows"
(before `</SidebarContent>`), using the same `SidebarMenuButton render={...}`
pattern as the NAV loop:

```tsx
import { Settings } from "lucide-react";
// below the Workflows SidebarGroup:
<SidebarGroup className="px-3">
  <SidebarGroupContent>
    <SidebarMenu className="gap-1">
      <SidebarMenuItem>
        <SidebarMenuButton
          className="h-10 rounded-lg px-3 text-[0.95rem]"
          render={
            <NavLink to="/settings">
              <Settings className="size-4" aria-hidden="true" />
              <span>Settings</span>
            </NavLink>
          }
        />
      </SidebarMenuItem>
    </SidebarMenu>
  </SidebarGroupContent>
</SidebarGroup>
```

- [ ] **Step 4: Run tests, lint**

Run: `cd web && npx vitest run src/features/settings && npm run lint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/features/settings web/src/app
git commit -m "feat(web): settings shell with secondary nav and sidebar entry"
```

---

### Task 2: Config data hooks + SaveBar (shared dirty-form machinery)

**Files:**
- Create: `web/src/features/settings/use-config.ts`
- Create: `web/src/features/settings/SaveBar.tsx`
- Test: `web/src/features/settings/use-config.test.tsx`

**Interfaces:**
- Consumes: `api`, `unwrap` from `@/lib/api/client`; generated `paths` types.
- Produces:
  - `useConfig<P extends ConfigPath>(path: P)` → TanStack `useQuery` keyed `["config", path]` returning the GET body.
  - `useSaveConfig<P>(path: P)` → mutation PUTting the full document, updating the query cache on success and toasting "Saved".
  - `ConfigPath` union type: `"/api/config/search" | "/api/config/review" | "/api/config/prune" | "/api/config/render" | "/api/config/style-guide" | "/api/config/profile" | "/api/config/models"`.
  - `SaveBar({ dirty, saving, onSave, onDiscard })` — sticky footer bar, hidden until `dirty`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/settings/use-config.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { useConfig, useSaveConfig } from "./use-config";

const server = setupServer(
  http.get("*/api/config/prune", () =>
    HttpResponse.json({ fitThreshold: 40, staleDays: 60, retentionDays: 30,
      enableRejected: true, enableLowFit: true, enableStale: true }),
  ),
  http.put("*/api/config/prune", async ({ request }) =>
    HttpResponse.json(await request.json()),
  ),
);
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useConfig", () => {
  it("fetches the config document", async () => {
    const { result } = renderHook(() => useConfig("/api/config/prune"), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.fitThreshold).toBe(40);
  });

  it("save mutation PUTs and resolves with the echoed doc", async () => {
    const { result } = renderHook(() => useSaveConfig("/api/config/prune"), { wrapper });
    const saved = await result.current.mutateAsync({
      fitThreshold: 55, staleDays: 60, retentionDays: 30,
      enableRejected: false, enableLowFit: true, enableStale: true,
    });
    expect(saved.fitThreshold).toBe(55);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/settings/use-config.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement hooks + SaveBar**

```tsx
// web/src/features/settings/use-config.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { paths } from "@/lib/api/schema";

export type ConfigPath =
  | "/api/config/search"
  | "/api/config/review"
  | "/api/config/prune"
  | "/api/config/render"
  | "/api/config/style-guide"
  | "/api/config/profile"
  | "/api/config/models";

type GetBody<P extends ConfigPath> =
  paths[P]["get"]["responses"][200]["content"]["application/json"];

export function useConfig<P extends ConfigPath>(path: P) {
  return useQuery({
    queryKey: ["config", path],
    queryFn: () => unwrap(api.GET(path)) as Promise<GetBody<P>>,
  });
}

export function useSaveConfig<P extends ConfigPath>(path: P) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: GetBody<P>) =>
      unwrap(api.PUT(path, { body: body as never })) as Promise<GetBody<P>>,
    onSuccess: (saved) => {
      qc.setQueryData(["config", path], saved);
      toast.success("Saved");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}
```

```tsx
// web/src/features/settings/SaveBar.tsx
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

export function SaveBar({
  dirty, saving, onSave, onDiscard,
}: {
  dirty: boolean; saving: boolean; onSave: () => void; onDiscard: () => void;
}) {
  if (!dirty) return null;
  return (
    <div className="sticky bottom-0 z-10 mt-6 flex items-center gap-3 rounded-lg border bg-background/95 p-3 backdrop-blur">
      <span className="text-sm text-muted-foreground">You have unsaved changes</span>
      <div className="ml-auto flex gap-2">
        <Button variant="outline" onClick={onDiscard} disabled={saving}>
          Discard
        </Button>
        <Button onClick={onSave} disabled={saving}>
          {saving ? <Spinner data-icon="inline-start" /> : null}
          Save changes
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests, lint, commit**

```bash
cd web && npx vitest run src/features/settings && npm run lint
git add web/src/features/settings
git commit -m "feat(web): shared config query/save hooks and SaveBar"
```

---

### Task 3: Search settings page (form shared with the wizard)

**Files:**
- Create: `web/src/features/settings/forms/TagListInput.tsx`
- Create: `web/src/features/settings/forms/SearchConfigForm.tsx`
- Create: `web/src/features/settings/pages/SearchSettingsPage.tsx`
- Modify: `web/src/app/router.tsx` (register `/settings/search`)
- Test: `web/src/features/settings/forms/SearchConfigForm.test.tsx`

**Interfaces:**
- Consumes: `useConfig`/`useSaveConfig` (Task 2), shadcn `Field`/`FieldGroup`/`Input`/`Switch`/`ToggleGroup`/`Badge`.
- Produces:
  - `TagListInput({ id, value, onChange, placeholder })` — Enter/comma adds a tag (rendered as `Badge` with an ✕ button), Backspace on empty input removes the last.
  - `SearchConfigForm({ value, onChange })` — controlled; parent owns state/dirty tracking. Covers: keywords, titles, locations (TagListInput), remotePolicy (`ToggleGroup`: any/remote_only/hybrid/onsite), minSalary/yoeMin/yoeMax (numeric `Input`), sponsorshipRequired (`Switch`), plus a collapsed `Accordion` "Relevance tuning" with roleAnchors/excludeTerms (TagListInput) and targetRole (`Input`).
  - `SearchSettingsPage()` — loads via `useConfig("/api/config/search")`, local draft state, `SaveBar`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/settings/forms/SearchConfigForm.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { SearchConfigForm, type SearchDoc } from "./SearchConfigForm";

const EMPTY: SearchDoc = {
  keywords: [], titles: [], locations: [], remotePolicy: null,
  minSalary: null, yoeMin: null, yoeMax: null, sponsorshipRequired: false,
  roleAnchors: [], excludeTerms: [], targetRole: null,
  distance: null, maxDaysOld: null, experienceLevels: [], employmentTypes: [],
};

function Harness() {
  const [value, setValue] = useState(EMPTY);
  return (
    <>
      <SearchConfigForm value={value} onChange={setValue} />
      <output data-testid="keywords">{value.keywords.join(",")}</output>
    </>
  );
}

describe("SearchConfigForm", () => {
  it("adds a keyword tag on Enter", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Keywords"), "python{Enter}");
    expect(screen.getByTestId("keywords")).toHaveTextContent("python");
  });

  it("removes a tag via its remove button", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText("Keywords"), "python{Enter}");
    await user.click(screen.getByRole("button", { name: "Remove python" }));
    expect(screen.getByTestId("keywords")).toHaveTextContent("");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/settings/forms/SearchConfigForm.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement TagListInput + form + page**

```tsx
// web/src/features/settings/forms/TagListInput.tsx
import { useState } from "react";
import { X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

export function TagListInput({
  id, value, onChange, placeholder,
}: {
  id: string; value: string[]; onChange: (next: string[]) => void; placeholder?: string;
}) {
  const [draft, setDraft] = useState("");

  const commit = () => {
    const tag = draft.trim().replace(/,+$/, "");
    if (tag && !value.includes(tag)) onChange([...value, tag]);
    setDraft("");
  };

  return (
    <div className="flex flex-col gap-2">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((tag) => (
            <Badge key={tag} variant="secondary" className="gap-1">
              {tag}
              <button
                type="button"
                aria-label={`Remove ${tag}`}
                className="rounded-sm hover:text-destructive"
                onClick={() => onChange(value.filter((t) => t !== tag))}
              >
                <X className="size-3" aria-hidden="true" />
              </button>
            </Badge>
          ))}
        </div>
      )}
      <Input
        id={id}
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commit();
          } else if (e.key === "Backspace" && draft === "" && value.length > 0) {
            onChange(value.slice(0, -1));
          }
        }}
      />
    </div>
  );
}
```

```tsx
// web/src/features/settings/forms/SearchConfigForm.tsx
import {
  Accordion, AccordionContent, AccordionItem, AccordionTrigger,
} from "@/components/ui/accordion";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { paths } from "@/lib/api/schema";

import { TagListInput } from "./TagListInput";

export type SearchDoc =
  paths["/api/config/search"]["get"]["responses"][200]["content"]["application/json"];

const REMOTE_OPTIONS = [
  { value: "any", label: "Any" },
  { value: "remote_only", label: "Remote only" },
  { value: "hybrid", label: "Hybrid" },
  { value: "onsite", label: "On-site" },
];

function numOrNull(raw: string): number | null {
  return raw === "" ? null : Number(raw);
}

export function SearchConfigForm({
  value, onChange,
}: {
  value: SearchDoc; onChange: (next: SearchDoc) => void;
}) {
  const set = <K extends keyof SearchDoc>(key: K, v: SearchDoc[K]) =>
    onChange({ ...value, [key]: v });

  return (
    <FieldGroup>
      <Field>
        <FieldLabel htmlFor="keywords">Keywords</FieldLabel>
        <TagListInput id="keywords" value={value.keywords ?? []}
          onChange={(v) => set("keywords", v)} placeholder="python, distributed systems…" />
      </Field>
      <Field>
        <FieldLabel htmlFor="titles">Titles</FieldLabel>
        <TagListInput id="titles" value={value.titles ?? []}
          onChange={(v) => set("titles", v)} placeholder="Software Engineer…" />
      </Field>
      <Field>
        <FieldLabel htmlFor="locations">Locations</FieldLabel>
        <TagListInput id="locations" value={value.locations ?? []}
          onChange={(v) => set("locations", v)} placeholder="Remote, Austin TX…" />
      </Field>
      <Field>
        <FieldLabel>Remote policy</FieldLabel>
        <ToggleGroup
          type="single"
          value={value.remotePolicy ?? "any"}
          onValueChange={(v: string) => set("remotePolicy", v === "any" ? null : v)}
        >
          {REMOTE_OPTIONS.map((o) => (
            <ToggleGroupItem key={o.value} value={o.value}>{o.label}</ToggleGroupItem>
          ))}
        </ToggleGroup>
      </Field>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Field>
          <FieldLabel htmlFor="minSalary">Minimum salary</FieldLabel>
          <Input id="minSalary" type="number" value={value.minSalary ?? ""}
            onChange={(e) => set("minSalary", numOrNull(e.target.value))} />
        </Field>
        <Field>
          <FieldLabel htmlFor="yoeMin">Years of experience, min</FieldLabel>
          <Input id="yoeMin" type="number" value={value.yoeMin ?? ""}
            onChange={(e) => set("yoeMin", numOrNull(e.target.value))} />
        </Field>
        <Field>
          <FieldLabel htmlFor="yoeMax">Years of experience, max</FieldLabel>
          <Input id="yoeMax" type="number" value={value.yoeMax ?? ""}
            onChange={(e) => set("yoeMax", numOrNull(e.target.value))} />
        </Field>
      </div>
      <Field>
        <div className="flex items-center gap-3">
          <Switch id="sponsorship" checked={value.sponsorshipRequired ?? false}
            onCheckedChange={(v: boolean) => set("sponsorshipRequired", v)} />
          <FieldLabel htmlFor="sponsorship">I need visa sponsorship</FieldLabel>
        </div>
      </Field>
      <Accordion type="single" collapsible>
        <AccordionItem value="tuning">
          <AccordionTrigger>Relevance tuning</AccordionTrigger>
          <AccordionContent>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="roleAnchors">Role anchors</FieldLabel>
                <TagListInput id="roleAnchors" value={value.roleAnchors ?? []}
                  onChange={(v) => set("roleAnchors", v)} />
              </Field>
              <Field>
                <FieldLabel htmlFor="excludeTerms">Exclude terms</FieldLabel>
                <TagListInput id="excludeTerms" value={value.excludeTerms ?? []}
                  onChange={(v) => set("excludeTerms", v)} />
              </Field>
              <Field>
                <FieldLabel htmlFor="targetRole">Target role</FieldLabel>
                <Input id="targetRole" value={value.targetRole ?? ""}
                  onChange={(e) => set("targetRole", e.target.value || null)} />
              </Field>
            </FieldGroup>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </FieldGroup>
  );
}
```

Check the installed `ToggleGroup`/`Switch`/`Accordion` prop names against
`web/src/components/ui/*.tsx` before finalizing (base-ui flavored components
may use `onValueChange`/`onCheckedChange` or plain `onChange` — mirror what the
installed source exports; adjust the form to match).

```tsx
// web/src/features/settings/pages/SearchSettingsPage.tsx
import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { SearchConfigForm, type SearchDoc } from "../forms/SearchConfigForm";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig } from "../use-config";

export function SearchSettingsPage() {
  const { data } = useConfig("/api/config/search");
  const save = useSaveConfig("/api/config/search");
  const [draft, setDraft] = useState<SearchDoc | null>(null);

  useEffect(() => {
    if (data && draft === null) setDraft(data);
  }, [data, draft]);

  if (!data || !draft) return <Skeleton className="h-64 w-full" />;
  const dirty = JSON.stringify(draft) !== JSON.stringify(data);

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-lg font-semibold">Search</h1>
        <p className="text-sm text-muted-foreground">
          What discovery looks for. Tighter role anchors mean fewer wasted fetches.
        </p>
      </header>
      <SearchConfigForm value={draft} onChange={setDraft} />
      <SaveBar
        dirty={dirty}
        saving={save.isPending}
        onSave={() => save.mutate(draft, { onSuccess: (saved) => setDraft(saved) })}
        onDiscard={() => setDraft(data)}
      />
    </div>
  );
}
```

Register in `router.tsx` under the settings children:

```tsx
const SearchSettingsPage = lazy(() =>
  import("@/features/settings/pages/SearchSettingsPage").then((m) => ({ default: m.SearchSettingsPage })),
);
// children of "settings":
{ path: "search", element: page(<SearchSettingsPage />) },
```

- [ ] **Step 4: Run tests, lint, commit**

```bash
cd web && npx vitest run src/features/settings && npm run lint
git add web/src/features/settings web/src/app/router.tsx
git commit -m "feat(web): search settings page with shared SearchConfigForm"
```

---

### Task 4: API keys page (secrets + models)

**Files:**
- Create: `web/src/features/settings/use-secrets.ts`
- Create: `web/src/features/settings/forms/SecretsForm.tsx`
- Create: `web/src/features/settings/pages/KeysSettingsPage.tsx`
- Modify: `web/src/app/router.tsx` (register `/settings/keys`)
- Test: `web/src/features/settings/forms/SecretsForm.test.tsx`

**Interfaces:**
- Consumes: `GET/PUT /api/secrets` (list of `{key, isSet, hint}`), `useConfig("/api/config/models")` + `useSaveConfig`.
- Produces:
  - `useSecrets()` — query `["secrets"]`; `useSaveSecrets()` — mutation PUTting a partial `{[camelKey]: string | null}` map, invalidating `["secrets"]` and `["setup-status"]`.
  - `SecretsForm({ statuses, onSave, saving })` — one row per key: label, status (`Badge` "Set · ••••abc4" or "Not set"), and a password `Input` + "Save key" that appears via a "Replace"/"Add" toggle; set keys also get "Clear" (sends `null`).
  - `SECRET_LABELS` map: anthropicApiKey → "Anthropic API key", openaiApiKey → "OpenAI API key", geminiApiKey → "Gemini API key", deepseekApiKey → "DeepSeek API key", githubToken → "GitHub token", adzunaAppId → "Adzuna app ID", adzunaAppKey → "Adzuna app key", linkedinEmail → "LinkedIn email", linkedinPassword → "LinkedIn password".
  - `KeysSettingsPage()` — SecretsForm section + "Model tiers" section (three `Input`s for cheapModel/midModel/premiumModel with a SaveBar).

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/settings/forms/SecretsForm.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SecretsForm } from "./SecretsForm";

const STATUSES = [
  { key: "anthropicApiKey", isSet: true, hint: "cd12" },
  { key: "openaiApiKey", isSet: false, hint: null },
];

describe("SecretsForm", () => {
  it("shows hint for set keys and never a value input by default", () => {
    render(<SecretsForm statuses={STATUSES} saving={false} onSave={vi.fn()} />);
    expect(screen.getByText(/cd12/)).toBeInTheDocument();
    expect(screen.queryAllByLabelText(/new value/i)).toHaveLength(0);
  });

  it("saves a newly entered key", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(<SecretsForm statuses={STATUSES} saving={false} onSave={onSave} />);
    await user.click(screen.getByRole("button", { name: "Add OpenAI API key" }));
    await user.type(screen.getByLabelText("OpenAI API key new value"), "sk-oai-123");
    await user.click(screen.getByRole("button", { name: "Save key" }));
    expect(onSave).toHaveBeenCalledWith({ openaiApiKey: "sk-oai-123" });
  });

  it("clears a set key with null", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(<SecretsForm statuses={STATUSES} saving={false} onSave={onSave} />);
    await user.click(screen.getByRole("button", { name: "Clear Anthropic API key" }));
    expect(onSave).toHaveBeenCalledWith({ anthropicApiKey: null });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/settings/forms/SecretsForm.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement hooks + form + page**

```tsx
// web/src/features/settings/use-secrets.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";

export type SecretStatus = { key: string; isSet: boolean; hint: string | null };
export type SecretsPatch = Record<string, string | null>;

export function useSecrets() {
  return useQuery({
    queryKey: ["secrets"],
    queryFn: () => unwrap(api.GET("/api/secrets")) as Promise<SecretStatus[]>,
  });
}

export function useSaveSecrets() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: SecretsPatch) =>
      unwrap(api.PUT("/api/secrets", { body: patch as never })) as Promise<SecretStatus[]>,
    onSuccess: (statuses) => {
      qc.setQueryData(["secrets"], statuses);
      qc.invalidateQueries({ queryKey: ["setup-status"] });
      toast.success("Keys updated");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}
```

```tsx
// web/src/features/settings/forms/SecretsForm.tsx
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import type { SecretsPatch, SecretStatus } from "../use-secrets";

export const SECRET_LABELS: Record<string, string> = {
  anthropicApiKey: "Anthropic API key",
  openaiApiKey: "OpenAI API key",
  geminiApiKey: "Gemini API key",
  deepseekApiKey: "DeepSeek API key",
  githubToken: "GitHub token",
  adzunaAppId: "Adzuna app ID",
  adzunaAppKey: "Adzuna app key",
  linkedinEmail: "LinkedIn email",
  linkedinPassword: "LinkedIn password",
};

export function SecretsForm({
  statuses, saving, onSave,
}: {
  statuses: SecretStatus[]; saving: boolean; onSave: (patch: SecretsPatch) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const startEdit = (key: string) => {
    setEditing(key);
    setDraft("");
  };

  return (
    <FieldGroup>
      {statuses.map((s) => {
        const label = SECRET_LABELS[s.key] ?? s.key;
        return (
          <Field key={s.key}>
            <div className="flex flex-wrap items-center gap-3">
              <FieldLabel className="min-w-44">{label}</FieldLabel>
              {s.isSet ? (
                <Badge variant="secondary">Set{s.hint ? ` · ••••${s.hint}` : ""}</Badge>
              ) : (
                <Badge variant="outline">Not set</Badge>
              )}
              <div className="ml-auto flex gap-2">
                {editing !== s.key && (
                  <Button variant="outline" size="sm" onClick={() => startEdit(s.key)}>
                    {s.isSet ? `Replace ${label}` : `Add ${label}`}
                  </Button>
                )}
                {s.isSet && (
                  <Button variant="outline" size="sm" disabled={saving}
                    aria-label={`Clear ${label}`}
                    onClick={() => onSave({ [s.key]: null })}>
                    Clear {label}
                  </Button>
                )}
              </div>
            </div>
            {editing === s.key && (
              <div className="mt-2 flex gap-2">
                <Input
                  type="password"
                  aria-label={`${label} new value`}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  autoComplete="off"
                />
                <Button disabled={saving || draft === ""}
                  onClick={() => { onSave({ [s.key]: draft }); setEditing(null); }}>
                  Save key
                </Button>
                <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
              </div>
            )}
          </Field>
        );
      })}
    </FieldGroup>
  );
}
```

```tsx
// web/src/features/settings/pages/KeysSettingsPage.tsx
import { useEffect, useState } from "react";

import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { SecretsForm } from "../forms/SecretsForm";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig } from "../use-config";
import { useSaveSecrets, useSecrets } from "../use-secrets";

type ModelsDoc = { cheapModel: string; midModel: string; premiumModel: string };

const MODEL_FIELDS: { key: keyof ModelsDoc; label: string }[] = [
  { key: "cheapModel", label: "Cheap tier model" },
  { key: "midModel", label: "Mid tier model" },
  { key: "premiumModel", label: "Premium tier model" },
];

export function KeysSettingsPage() {
  const secrets = useSecrets();
  const saveSecrets = useSaveSecrets();
  const models = useConfig("/api/config/models");
  const saveModels = useSaveConfig("/api/config/models");
  const [draft, setDraft] = useState<ModelsDoc | null>(null);

  useEffect(() => {
    if (models.data && draft === null) setDraft(models.data as ModelsDoc);
  }, [models.data, draft]);

  if (!secrets.data || !models.data || !draft) return <Skeleton className="h-64 w-full" />;
  const dirty = JSON.stringify(draft) !== JSON.stringify(models.data);

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-lg font-semibold">API keys</h1>
        <p className="text-sm text-muted-foreground">
          Keys are write-only: once saved, only the last four characters are shown.
        </p>
      </header>
      <SecretsForm statuses={secrets.data} saving={saveSecrets.isPending}
        onSave={(patch) => saveSecrets.mutate(patch)} />
      <Separator />
      <section className="flex flex-col gap-4">
        <h2 className="text-sm font-medium">Model tiers</h2>
        <FieldGroup>
          {MODEL_FIELDS.map((f) => (
            <Field key={f.key}>
              <FieldLabel htmlFor={f.key}>{f.label}</FieldLabel>
              <Input id={f.key} value={draft[f.key]}
                onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} />
            </Field>
          ))}
        </FieldGroup>
        <SaveBar dirty={dirty} saving={saveModels.isPending}
          onSave={() => saveModels.mutate(draft as never)}
          onDiscard={() => setDraft(models.data as ModelsDoc)} />
      </section>
    </div>
  );
}
```

Register `/settings/keys` in `router.tsx` (lazy, same pattern as Task 3).

- [ ] **Step 4: Run tests, lint, commit**

```bash
cd web && npx vitest run src/features/settings && npm run lint
git add web/src/features/settings web/src/app/router.tsx
git commit -m "feat(web): API keys page with write-only secrets and model tiers"
```

---

### Task 5: Review, Rendering, Pruning settings pages

**Files:**
- Create: `web/src/features/settings/pages/ReviewSettingsPage.tsx`
- Create: `web/src/features/settings/pages/RenderingSettingsPage.tsx`
- Create: `web/src/features/settings/pages/PruningSettingsPage.tsx`
- Modify: `web/src/app/router.tsx` (register the three routes)
- Test: `web/src/features/settings/pages/PruningSettingsPage.test.tsx`

**Interfaces:**
- Consumes: `useConfig`/`useSaveConfig`/`SaveBar` (Task 2); shadcn `Table`, `Select`, `Switch`, `Alert`.
- Produces: three pages, each following the SearchSettingsPage load→draft→dirty→SaveBar pattern.

All three pages copy the exact state pattern from `SearchSettingsPage`
(`useConfig` → `useState` draft seeded in `useEffect` → `JSON.stringify` dirty
check → `SaveBar`). The bodies differ:

**PruningSettingsPage** — numeric `Input`s for fitThreshold/staleDays/retentionDays,
`Switch` rows for enableRejected ("Archive jobs the discovery filter already rejected"),
enableLowFit ("Archive scored jobs below the fit threshold"),
enableStale ("Archive jobs older than the stale window").

**RenderingSettingsPage** — two `Input`s: templatePath ("Template path" —
description: "Typst template used for rendered resumes") and outputDir
("Output directory").

**ReviewSettingsPage** — numeric `Input`s for maxRounds and scoreThreshold; a
`Table` with one row per reviewer: name (read-only text), gate `Switch`, weight
numeric `Input`, modelTier `Select` (cheap/mid/premium); the fact-check row
shows a muted note "Blocking — unsupported claims fail the round" under the
name. A `FieldSet` "Length budget" with three numeric inputs
(maxExperiences/maxBulletsPerRole/targetTotalBullets) and a `Switch` to
enable/disable the block (null lengthBudget = disabled → send `null`). Above
the form, an `Alert`: "Defaults are sensible — change reviewer weights only if
you know why."

- [ ] **Step 1: Write the failing test (pruning page as the representative)**

```tsx
// web/src/features/settings/pages/PruningSettingsPage.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { PruningSettingsPage } from "./PruningSettingsPage";

const DOC = { fitThreshold: 40, staleDays: 60, retentionDays: 30,
  enableRejected: true, enableLowFit: true, enableStale: true };
let lastPut: unknown = null;

const server = setupServer(
  http.get("*/api/config/prune", () => HttpResponse.json(DOC)),
  http.put("*/api/config/prune", async ({ request }) => {
    lastPut = await request.json();
    return HttpResponse.json(lastPut);
  }),
);
beforeAll(() => server.listen());
afterEach(() => { server.resetHandlers(); lastPut = null; });
afterAll(() => server.close());

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}><PruningSettingsPage /></QueryClientProvider>,
  );
}

describe("PruningSettingsPage", () => {
  it("shows SaveBar only after an edit, then PUTs the full document", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("Fit threshold")).toBeInTheDocument());
    expect(screen.queryByText(/unsaved changes/i)).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText("Fit threshold"));
    await user.type(screen.getByLabelText("Fit threshold"), "55");
    expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(lastPut).toMatchObject({ fitThreshold: 55 }));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/settings/pages/PruningSettingsPage.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement the three pages**

`PruningSettingsPage` in full (the other two repeat the pattern with their
fields as described above — write them out completely, no shared abstraction
beyond `SaveBar`/`useConfig`):

```tsx
// web/src/features/settings/pages/PruningSettingsPage.tsx
import { useEffect, useState } from "react";

import { Field, FieldGroup, FieldLabel, FieldDescription } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig } from "../use-config";
import type { paths } from "@/lib/api/schema";

type PruneDoc = paths["/api/config/prune"]["get"]["responses"][200]["content"]["application/json"];

const RULES: { key: "enableRejected" | "enableLowFit" | "enableStale"; label: string; help: string }[] = [
  { key: "enableRejected", label: "Archive rejected jobs",
    help: "Jobs the discovery filter already rejected" },
  { key: "enableLowFit", label: "Archive low-fit jobs",
    help: "Scored jobs below the fit threshold" },
  { key: "enableStale", label: "Archive stale jobs",
    help: "Postings older than the stale window" },
];

export function PruningSettingsPage() {
  const { data } = useConfig("/api/config/prune");
  const save = useSaveConfig("/api/config/prune");
  const [draft, setDraft] = useState<PruneDoc | null>(null);

  useEffect(() => {
    if (data && draft === null) setDraft(data);
  }, [data, draft]);

  if (!data || !draft) return <Skeleton className="h-64 w-full" />;
  const dirty = JSON.stringify(draft) !== JSON.stringify(data);
  const setNum = (key: keyof PruneDoc) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setDraft({ ...draft, [key]: Number(e.target.value || 0) });

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-lg font-semibold">Pruning</h1>
        <p className="text-sm text-muted-foreground">
          Archiving is reversible and never touches jobs you have progressed.
        </p>
      </header>
      <FieldGroup>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field>
            <FieldLabel htmlFor="fitThreshold">Fit threshold</FieldLabel>
            <Input id="fitThreshold" type="number" value={draft.fitThreshold}
              onChange={setNum("fitThreshold")} />
            <FieldDescription>Archive scored jobs below this fit score</FieldDescription>
          </Field>
          <Field>
            <FieldLabel htmlFor="staleDays">Stale after (days)</FieldLabel>
            <Input id="staleDays" type="number" value={draft.staleDays}
              onChange={setNum("staleDays")} />
          </Field>
          <Field>
            <FieldLabel htmlFor="retentionDays">Delete archived after (days)</FieldLabel>
            <Input id="retentionDays" type="number" value={draft.retentionDays}
              onChange={setNum("retentionDays")} />
          </Field>
        </div>
        {RULES.map((rule) => (
          <Field key={rule.key}>
            <div className="flex items-center gap-3">
              <Switch id={rule.key} checked={draft[rule.key]}
                onCheckedChange={(v: boolean) => setDraft({ ...draft, [rule.key]: v })} />
              <div>
                <FieldLabel htmlFor={rule.key}>{rule.label}</FieldLabel>
                <FieldDescription>{rule.help}</FieldDescription>
              </div>
            </div>
          </Field>
        ))}
      </FieldGroup>
      <SaveBar dirty={dirty} saving={save.isPending}
        onSave={() => save.mutate(draft)} onDiscard={() => setDraft(data)} />
    </div>
  );
}
```

Write `RenderingSettingsPage.tsx` and `ReviewSettingsPage.tsx` following the
same skeleton with the fields specified in the Interfaces block. Register all
three in `router.tsx`: `review`, `rendering`, `pruning`.

- [ ] **Step 4: Run tests, lint, commit**

```bash
cd web && npx vitest run src/features/settings && npm run lint
git add web/src/features/settings web/src/app/router.tsx
git commit -m "feat(web): review, rendering, and pruning settings pages"
```

---

### Task 6: Style guide page (adds textarea component)

**Files:**
- Create: `web/src/components/ui/textarea.tsx` (via shadcn CLI)
- Create: `web/src/features/settings/pages/StyleGuideSettingsPage.tsx`
- Modify: `web/src/app/router.tsx` (register `style-guide`)
- Test: `web/src/features/settings/pages/StyleGuideSettingsPage.test.tsx`

- [ ] **Step 1: Add the textarea component**

Run: `cd web && npx shadcn@latest add textarea`
Then read the added file and confirm it matches the installed base-ui flavor.

- [ ] **Step 2: Write the failing test**

```tsx
// web/src/features/settings/pages/StyleGuideSettingsPage.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { StyleGuideSettingsPage } from "./StyleGuideSettingsPage";

let lastPut: unknown = null;
const server = setupServer(
  http.get("*/api/config/style-guide", () => HttpResponse.json({ content: "# Voice" })),
  http.put("*/api/config/style-guide", async ({ request }) => {
    lastPut = await request.json();
    return HttpResponse.json(lastPut);
  }),
);
beforeAll(() => server.listen());
afterEach(() => { server.resetHandlers(); lastPut = null; });
afterAll(() => server.close());

describe("StyleGuideSettingsPage", () => {
  it("edits and saves the markdown content", async () => {
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><StyleGuideSettingsPage /></QueryClientProvider>);
    const box = await waitFor(() => screen.getByLabelText("Style guide"));
    await user.type(box, "\nBe concrete.");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect((lastPut as { content: string }).content).toContain("Be concrete."));
  });
});
```

- [ ] **Step 3: Run test to verify it fails, then implement**

```tsx
// web/src/features/settings/pages/StyleGuideSettingsPage.tsx
import { useEffect, useState } from "react";

import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { SaveBar } from "../SaveBar";
import { useConfig, useSaveConfig } from "../use-config";

export function StyleGuideSettingsPage() {
  const { data } = useConfig("/api/config/style-guide");
  const save = useSaveConfig("/api/config/style-guide");
  const [draft, setDraft] = useState<string | null>(null);

  useEffect(() => {
    if (data && draft === null) setDraft(data.content);
  }, [data, draft]);

  if (!data || draft === null) return <Skeleton className="h-64 w-full" />;
  const dirty = draft !== data.content;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-lg font-semibold">Style guide</h1>
        <p className="text-sm text-muted-foreground">
          House style for tailored bullets — the tailor and reviewers read this.
        </p>
      </header>
      <Field>
        <FieldLabel htmlFor="style-guide">Style guide</FieldLabel>
        <Textarea id="style-guide" value={draft} rows={20}
          className="font-mono text-sm"
          onChange={(e) => setDraft(e.target.value)} />
        <FieldDescription>{draft.length} characters · Markdown</FieldDescription>
      </Field>
      <SaveBar dirty={dirty} saving={save.isPending}
        onSave={() => save.mutate({ content: draft })}
        onDiscard={() => setDraft(data.content)} />
    </div>
  );
}
```

Register `style-guide` in `router.tsx`.

- [ ] **Step 4: Run tests, lint, commit**

```bash
cd web && npx vitest run src/features/settings && npm run lint
git add web/src/components/ui/textarea.tsx web/src/features/settings web/src/app/router.tsx
git commit -m "feat(web): style guide editor page"
```

---

### Task 7: Profile & documents page (upload, list, delete, rebuild)

**Files:**
- Create: `web/src/features/settings/use-documents.ts`
- Create: `web/src/features/settings/forms/DocumentManager.tsx`
- Create: `web/src/features/settings/pages/ProfileSettingsPage.tsx`
- Modify: `web/src/app/router.tsx` (register `profile`)
- Test: `web/src/features/settings/forms/DocumentManager.test.tsx`

**Interfaces:**
- Consumes: `GET/POST/DELETE /api/profile/documents`, `POST /api/profile/build`, `useConfig("/api/config/profile")`; the existing run-launch machinery — read `web/src/features/runs/use-launch-run.ts` first and reuse it for the build run (it owns registering the run in the RunPanel store); `GET /api/setup/status` invalidation.
- Produces:
  - `useDocuments()` (query `["profile-documents"]`), `useUploadDocument()` (multipart POST via `fetch` — openapi-fetch and multipart don't mix well; POST with `FormData` directly to `/api/profile/documents`, headers from the token helper), `useDeleteDocument()`.
  - `DocumentManager()` — drag-and-drop zone (native `onDrop`/`onDragOver` on a styled div + hidden `<input type="file">` opened by a "Choose file" button), docType `Select` (resume/transcript/portfolio/other, default resume), table of documents (filename, type `Badge`, size, uploaded date, delete button with `AlertDialog` confirm).
  - `ProfileSettingsPage()` — DocumentManager + GitHub username field (saved via `/api/config/profile` + SaveBar) + facts status line ("Profile built <relative time>" from `setup/status`, or "Not built yet") + "Rebuild profile" button that launches the build run.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/settings/forms/DocumentManager.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { DocumentManager } from "./DocumentManager";

const DOCS = [{ id: "abc123", filename: "resume.pdf", docType: "resume",
  sizeBytes: 1234, uploadedAt: "2026-07-01T00:00:00+00:00" }];

const server = setupServer(
  http.get("*/api/profile/documents", () => HttpResponse.json(DOCS)),
  http.post("*/api/profile/documents", () =>
    HttpResponse.json({ id: "new456", filename: "transcript.pdf", docType: "transcript",
      sizeBytes: 99, uploadedAt: "2026-07-01T01:00:00+00:00" }, { status: 201 })),
  http.delete("*/api/profile/documents/abc123", () =>
    new HttpResponse(null, { status: 204 })),
);
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderManager() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><DocumentManager /></QueryClientProvider>);
}

describe("DocumentManager", () => {
  it("lists documents with their type", async () => {
    renderManager();
    await waitFor(() => expect(screen.getByText("resume.pdf")).toBeInTheDocument());
    expect(screen.getByText("resume")).toBeInTheDocument();
  });

  it("uploads a chosen file with the selected type", async () => {
    const user = userEvent.setup();
    renderManager();
    await waitFor(() => screen.getByText("resume.pdf"));
    const input = screen.getByTestId("file-input") as HTMLInputElement;
    await user.upload(input, new File(["x"], "transcript.pdf", { type: "application/pdf" }));
    await waitFor(() => expect(screen.getByText("transcript.pdf")).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails, then implement**

```tsx
// web/src/features/settings/use-documents.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, getToken, unwrap } from "@/lib/api/client";

export type ProfileDocument = {
  id: string; filename: string; docType: string; sizeBytes: number; uploadedAt: string;
};

export function useDocuments() {
  return useQuery({
    queryKey: ["profile-documents"],
    queryFn: () => unwrap(api.GET("/api/profile/documents")) as Promise<ProfileDocument[]>,
  });
}

async function postDocument(file: File, docType: string): Promise<ProfileDocument> {
  const form = new FormData();
  form.append("file", file);
  form.append("docType", docType);
  const headers: HeadersInit = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${window.location.origin}/api/profile/documents`, {
    method: "POST", body: form, headers,
  });
  const body = await resp.json();
  if (!resp.ok) throw new Error(body?.error?.message ?? "Upload failed");
  return body as ProfileDocument;
}

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, docType }: { file: File; docType: string }) =>
      postDocument(file, docType),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-documents"] });
      qc.invalidateQueries({ queryKey: ["setup-status"] });
      toast.success("Document uploaded");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) =>
      unwrap(api.DELETE("/api/profile/documents/{doc_id}", {
        params: { path: { doc_id: docId } },
      } as never)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-documents"] });
      qc.invalidateQueries({ queryKey: ["setup-status"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });
}
```

(Check the generated path parameter name in `web/src/lib/api/schema.ts` —
`doc_id` vs `docId` — and match it.)

```tsx
// web/src/features/settings/forms/DocumentManager.tsx
import { useRef, useState } from "react";
import { FileUp, Trash2 } from "lucide-react";

import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty } from "@/components/ui/empty";
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { useDeleteDocument, useDocuments, useUploadDocument } from "../use-documents";

const DOC_TYPES = ["resume", "transcript", "portfolio", "other"] as const;

export function DocumentManager() {
  const docs = useDocuments();
  const upload = useUploadDocument();
  const del = useDeleteDocument();
  const [docType, setDocType] = useState<string>("resume");
  const fileInput = useRef<HTMLInputElement>(null);

  const handleFiles = (files: FileList | null) => {
    if (files?.[0]) upload.mutate({ file: files[0], docType });
  };

  return (
    <div className="flex flex-col gap-4">
      <div
        className="flex flex-col items-center gap-3 rounded-lg border border-dashed p-8 text-center"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); handleFiles(e.dataTransfer.files); }}
      >
        <FileUp className="size-6 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">
          Drop a document here — PDF, DOCX, TXT, or Markdown, up to 15 MB
        </p>
        <div className="flex items-center gap-2">
          <Select value={docType} onValueChange={setDocType}>
            <SelectTrigger className="w-36" aria-label="Document type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {DOC_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
              </SelectGroup>
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => fileInput.current?.click()}>
            Choose file
          </Button>
          <input ref={fileInput} data-testid="file-input" type="file" className="hidden"
            accept=".pdf,.docx,.txt,.md" onChange={(e) => handleFiles(e.target.files)} />
        </div>
      </div>

      {docs.data && docs.data.length === 0 && (
        <Empty>No documents yet — your resume is the one that matters most.</Empty>
      )}
      {docs.data && docs.data.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>File</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Uploaded</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {docs.data.map((doc) => (
              <TableRow key={doc.id}>
                <TableCell className="font-medium">{doc.filename}</TableCell>
                <TableCell><Badge variant="secondary">{doc.docType}</Badge></TableCell>
                <TableCell className="text-muted-foreground">
                  {new Date(doc.uploadedAt).toLocaleDateString()}
                </TableCell>
                <TableCell className="text-right">
                  <AlertDialog>
                    <AlertDialogTrigger
                      render={
                        <Button variant="ghost" size="sm" aria-label={`Delete ${doc.filename}`}>
                          <Trash2 aria-hidden="true" />
                        </Button>
                      }
                    />
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Delete {doc.filename}?</AlertDialogTitle>
                        <AlertDialogDescription>
                          The file is removed permanently. Facts already extracted stay
                          until the next profile build.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={() => del.mutate(doc.id)}>
                          Delete document
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
```

(Verify `Empty`'s children API and `AlertDialogTrigger render=` against the
installed `web/src/components/ui/*.tsx` sources; adjust to their real props.)

`ProfileSettingsPage` composes: `<DocumentManager/>`, a GitHub username
`Input` with SaveBar over `/api/config/profile`, a facts-status line reading
the `["setup-status"]` query (`GET /api/setup/status` via a small
`useSetupStatus()` hook — add it to `use-documents.ts` or a new
`use-setup-status.ts`; the wizard reuses it in Task 8):

```tsx
// add to web/src/features/settings/use-setup-status.ts
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { paths } from "@/lib/api/schema";

export type SetupStatus =
  paths["/api/setup/status"]["get"]["responses"][200]["content"]["application/json"];

export function useSetupStatus() {
  return useQuery({
    queryKey: ["setup-status"],
    queryFn: () => unwrap(api.GET("/api/setup/status")) as Promise<SetupStatus>,
  });
}
```

The "Rebuild profile" button launches via the existing run hook (read
`web/src/features/runs/use-launch-run.ts` and call it the way `RunActions`
does, with the new `POST /api/profile/build` path) so progress appears in the
global `RunPanel`. On run completion, invalidate `["setup-status"]`.

Register `profile` in `router.tsx`.

- [ ] **Step 3: Run tests, lint, commit**

```bash
cd web && npx vitest run src/features/settings && npm run lint
git add web/src/features/settings web/src/app/router.tsx
git commit -m "feat(web): profile documents manager with upload and rebuild"
```

---

### Task 8: Setup wizard (shell, steps, gate, finish)

**Files:**
- Create: `web/src/features/setup/SetupWizard.tsx` (shell: stepper header + outlet)
- Create: `web/src/features/setup/steps/KeysStep.tsx`
- Create: `web/src/features/setup/steps/DocumentsStep.tsx`
- Create: `web/src/features/setup/steps/SearchStep.tsx`
- Create: `web/src/features/setup/steps/SourcesStep.tsx`
- Create: `web/src/features/setup/FinishStep.tsx`
- Create: `web/src/features/setup/SetupGate.tsx`
- Modify: `web/src/app/router.tsx` (wizard routes OUTSIDE `AppLayout`; gate wraps `/`)
- Test: `web/src/features/setup/SetupWizard.test.tsx`, `web/src/features/setup/SetupGate.test.tsx`

**Interfaces:**
- Consumes: `useSetupStatus` (Task 7), `SecretsForm`+`useSecrets` (Task 4), `DocumentManager` (Task 7), `SearchConfigForm`+`useConfig` (Task 3), the existing `SourcesPage` internals (Task 9 extracts `SourcesManager`; until then embed `SourcesPage` directly), run launch hook (Task 7 pattern).
- Produces:
  - Route `/setup` (own top-level route, NOT inside `AppLayout` — single-column, no sidebar) with children `keys`, `documents`, `search`, `sources`, `finish`; index redirects to the first incomplete step.
  - `STEPS` export: `[{ slug: "keys", label: "Keys", done: (s: SetupStatus) => s.secrets.anyLlmKey }, { slug: "documents", label: "Documents", done: (s) => s.profile.hasResume }, { slug: "search", label: "Search", done: (s) => s.search.configured }, { slug: "sources", label: "Sources", done: (s) => s.sources.enabledCount > 0 }]`.
  - `SetupGate({ children })` — wraps the app shell route: while `setup/status` loads, render children; when loaded, if `!complete` and `localStorage["resume-agent-setup-dismissed"] !== "1"`, `<Navigate to="/setup" replace />`. On fetch error: render children (fail-open, spec §7).
  - "Exit setup" sets the localStorage flag and navigates to `/`.

- [ ] **Step 1: Write the failing tests**

```tsx
// web/src/features/setup/SetupGate.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { SetupGate } from "./SetupGate";

const INCOMPLETE = {
  secrets: { anthropicKey: false, anyLlmKey: false },
  profile: { documentCount: 0, hasResume: false, factsBuiltAt: null, githubUsername: null },
  search: { configured: false }, sources: { enabledCount: 0 }, complete: false,
};

const server = setupServer(
  http.get("*/api/setup/status", () => HttpResponse.json(INCOMPLETE)),
);
beforeAll(() => server.listen());
beforeEach(() => localStorage.clear());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderGate() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<SetupGate><div>dashboard</div></SetupGate>} />
          <Route path="/setup" element={<div>wizard</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SetupGate", () => {
  it("redirects to /setup when setup is incomplete", async () => {
    renderGate();
    await waitFor(() => expect(screen.getByText("wizard")).toBeInTheDocument());
  });

  it("does not redirect when the user dismissed setup", async () => {
    localStorage.setItem("resume-agent-setup-dismissed", "1");
    renderGate();
    await waitFor(() => expect(screen.getByText("dashboard")).toBeInTheDocument());
  });

  it("fails open when the status endpoint errors", async () => {
    server.use(http.get("*/api/setup/status", () =>
      HttpResponse.json({ error: { code: "X", message: "boom" } }, { status: 500 })));
    renderGate();
    await waitFor(() => expect(screen.getByText("dashboard")).toBeInTheDocument());
  });
});
```

```tsx
// web/src/features/setup/SetupWizard.test.tsx — stepper resume logic
import { describe, expect, it } from "vitest";

import { firstIncompleteStep, STEPS } from "./SetupWizard";

const status = (over: object) => ({
  secrets: { anthropicKey: false, anyLlmKey: false },
  profile: { documentCount: 0, hasResume: false, factsBuiltAt: null, githubUsername: null },
  search: { configured: false }, sources: { enabledCount: 0 }, complete: false,
  ...over,
});

describe("firstIncompleteStep", () => {
  it("starts at keys on a fresh install", () => {
    expect(firstIncompleteStep(status({}))).toBe("keys");
  });
  it("resumes at search when keys and documents are done", () => {
    expect(
      firstIncompleteStep(status({
        secrets: { anthropicKey: true, anyLlmKey: true },
        profile: { documentCount: 1, hasResume: true, factsBuiltAt: null, githubUsername: null },
      })),
    ).toBe("search");
  });
  it("lands on finish when every step is done", () => {
    expect(
      firstIncompleteStep(status({
        secrets: { anthropicKey: true, anyLlmKey: true },
        profile: { documentCount: 1, hasResume: true, factsBuiltAt: null, githubUsername: null },
        search: { configured: true }, sources: { enabledCount: 2 },
      })),
    ).toBe("finish");
  });
  it("exposes exactly four steps", () => {
    expect(STEPS.map((s) => s.slug)).toEqual(["keys", "documents", "search", "sources"]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail, then implement**

Shell essentials (complete the component around this skeleton):

```tsx
// web/src/features/setup/SetupWizard.tsx (core exports)
import { Check } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useSetupStatus, type SetupStatus } from "@/features/settings/use-setup-status";

export const STEPS = [
  { slug: "keys", label: "Keys", done: (s: SetupStatus) => s.secrets.anyLlmKey },
  { slug: "documents", label: "Documents", done: (s: SetupStatus) => s.profile.hasResume },
  { slug: "search", label: "Search", done: (s: SetupStatus) => s.search.configured },
  { slug: "sources", label: "Sources", done: (s: SetupStatus) => s.sources.enabledCount > 0 },
] as const;

export function firstIncompleteStep(status: SetupStatus): string {
  return STEPS.find((step) => !step.done(status))?.slug ?? "finish";
}

export function SetupWizard() {
  const { data: status } = useSetupStatus();
  const navigate = useNavigate();
  return (
    <div className="mx-auto flex min-h-svh w-full max-w-2xl flex-col gap-8 px-5 py-10">
      <header className="flex items-center gap-3">
        <div className="text-[0.68rem] font-semibold uppercase tracking-[0.28em] text-primary">
          Resume Agent · First-run setup
        </div>
        <Button variant="ghost" size="sm" className="ml-auto"
          onClick={() => {
            localStorage.setItem("resume-agent-setup-dismissed", "1");
            navigate("/");
          }}>
          Exit setup
        </Button>
      </header>
      <nav aria-label="Setup steps" className="flex items-center gap-2">
        {STEPS.map((step, i) => (
          <div key={step.slug} className="flex items-center gap-2">
            {i > 0 && <div className="h-px w-6 bg-border" aria-hidden="true" />}
            <NavLink to={`/setup/${step.slug}`}
              className={({ isActive }) =>
                cn("flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm",
                   isActive && "border-primary font-medium")
              }>
              {status && step.done(status) && (
                <Check className="size-3.5 text-primary" aria-hidden="true" />
              )}
              {step.label}
            </NavLink>
          </div>
        ))}
      </nav>
      <main className="flex-1"><Outlet /></main>
    </div>
  );
}
```

Steps (each is a `Card` with title, one-line why, the shared form, and a footer
with "Skip for now" → `navigate` to the next step and "Save & continue" →
commit then navigate):

- `KeysStep` — `SecretsForm` limited to `anthropicApiKey` outside the
  accordion; remaining keys inside an `Accordion` "More providers & sources".
  Continue is enabled always (keys save individually via `useSaveSecrets`);
  the step's "why" line: "Needed for tailoring — everything else works without it."
- `DocumentsStep` — `DocumentManager` + GitHub username `Input` (PUT
  `/api/config/profile` on continue).
- `SearchStep` — `SearchConfigForm` with local draft; continue PUTs
  `/api/config/search`.
- `SourcesStep` — embeds the Sources management UI (after Task 9: `<SourcesManager />`).
- `FinishStep` — checklist rendered from `STEPS` × `useSetupStatus` + a
  "Build profile" `Button` (run-launch hook, kind `profile-build`) with inline
  progress (subscribe the run the same way `RunPanel` rows do — read
  `web/src/features/runs/RunPanel.tsx` first), success state "Profile built —
  N facts extracted" (from the run result payload `experiences`/`projects`),
  then "Go to dashboard" → sets the dismissed flag and navigates `/`.
- Wizard index route: reads `useSetupStatus`, `<Navigate to={firstIncompleteStep(status)} replace />`.

```tsx
// web/src/features/setup/SetupGate.tsx
import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { useSetupStatus } from "@/features/settings/use-setup-status";

export function SetupGate({ children }: { children: ReactNode }) {
  const { data, isError } = useSetupStatus();
  if (isError) return <>{children}</>; // fail open — never lock a working app
  if (!data) return <>{children}</>;   // loading: render normally, no flash-gate
  const dismissed = localStorage.getItem("resume-agent-setup-dismissed") === "1";
  if (!data.complete && !dismissed) return <Navigate to="/setup" replace />;
  return <>{children}</>;
}
```

Router changes: `/setup` becomes a sibling of the `AppLayout` route with its
own children (`keys`, `documents`, `search`, `sources`, `finish`, index
redirect); wrap the `AppLayout` element as
`element: <SetupGate><AppLayout /></SetupGate>`.

- [ ] **Step 3: Run tests, lint, full web suite**

```bash
cd web && npm run test:run && npm run lint && npm run build
```
Expected: all green; build succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/src/features/setup web/src/app/router.tsx
git commit -m "feat(web): four-step setup wizard with first-run gate and finish run"
```

---

### Task 9: Sources relocation (`/sources` → `/settings/sources`)

**Files:**
- Modify: `web/src/features/sources/SourcesPage.tsx` (extract `SourcesManager` — the page body without the page header — and re-export both)
- Modify: `web/src/app/router.tsx` (register `/settings/sources`; `/sources` becomes `<Navigate to="/settings/sources" replace />`)
- Modify: `web/src/app/AppLayout.tsx` (remove Sources from the Workflows NAV array — it now lives under Settings)
- Modify: `web/src/features/setup/steps/SourcesStep.tsx` (swap embedded `SourcesPage` for `SourcesManager`)
- Test: existing `web/src/features/sources/SourcesPage.test.tsx` must stay green; add a redirect assertion to the router if a router test file exists (check `web/src/app/` for tests; if none, skip — the e2e in Task 10 covers it).

- [ ] **Step 1: Extract `SourcesManager` from `SourcesPage`**

Read `web/src/features/sources/SourcesPage.tsx`; move everything below the
page-level header into `export function SourcesManager()` in the same file;
`SourcesPage` becomes header + `<SourcesManager />`. No behavior change.

- [ ] **Step 2: Rewire routes and nav** (as listed in Files)

- [ ] **Step 3: Run the whole web suite**

```bash
cd web && npm run test:run && npm run lint
```
Expected: green — if `SourcesPage.test.tsx` asserted the route, update it to the new path.

- [ ] **Step 4: Commit**

```bash
git add web/src
git commit -m "refactor(web): relocate sources under settings with redirect"
```

---

### Task 10: End-to-end smoke (first-run → wizard → settings)

**Files:**
- Create: `web/e2e/setup-wizard.spec.ts`
- Test: Playwright (`npm run e2e`) — check `web/playwright.config.ts` first for
  how the backend is provided (webServer block vs manual); follow the existing
  e2e specs' conventions (`Get-ChildItem web/e2e` — if the folder doesn't exist
  yet, check `playwright.config.ts` `testDir`).

- [ ] **Step 1: Write the smoke spec**

```ts
// web/e2e/setup-wizard.spec.ts
import { expect, test } from "@playwright/test";

// Serves the SPA against a fresh backend (empty config/env), so the gate fires.
test("first run gates to the wizard; exit reaches the app; settings nav works", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/setup/);
  await expect(page.getByText("First-run setup")).toBeVisible();

  await page.getByRole("button", { name: "Exit setup" }).click();
  await expect(page).not.toHaveURL(/\/setup/);

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL(/\/settings\/profile/);
  await page.getByRole("link", { name: "Search" }).click();
  await expect(page.getByLabelText("Keywords")).toBeVisible();
});
```

Adjust the empty-backend setup to the project's Playwright configuration (env
vars for `config_dir`/`env_path`/`data_dir` on the `resume-agent serve`
process, or a fixture that starts `create_app` with temp paths). If the
existing e2e infra cannot provide a fresh backend, mark the gate assertion
`test.skip` with a comment and keep the settings-nav portion.

- [ ] **Step 2: Run, fix, commit**

```bash
cd web && npm run e2e
git add web/e2e
git commit -m "test(web): setup wizard + settings e2e smoke"
```

---

## Self-review notes (already applied)

- Spec §4 wizard behaviors → Task 8 (gate, per-step commit, skip, resume, finish run, localStorage dismissal, fail-open).
- Spec §5 settings behaviors → Tasks 1–7, 9 (all eight areas incl. relocated Sources; shared forms wizard↔settings via Tasks 3/4/7 components).
- Type-consistency: `useSetupStatus`/`SetupStatus` defined once (Task 7) and consumed by Tasks 8; `SearchDoc` defined in Task 3 and reused; `SourcesManager` named identically in Tasks 8/9.
- Installed-component caveats are flagged where base-ui prop names may differ; implementers must read the installed `ui/*.tsx` source before use.
