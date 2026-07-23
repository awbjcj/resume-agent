import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type ZoomTransform } from "d3-zoom";
import { ArrowLeftIcon, Maximize2Icon, MinusIcon, PlusIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { cn } from "@/lib/utils";
import {
  targetId,
  UNASSIGNED_ID,
  type SkillRow,
  type SuggestionState,
  type SuggestionTarget,
  type CategoryRow,
} from "./aggregate";
import {
  buildGraph,
  drillTarget,
  parentView,
  recommendedLayoutHeight,
  runLayout,
  type MapView,
} from "./skill-map-layout";
import { AddSkillDialog } from "./taxonomy-edit/AddSkillDialog";
import { ChangeCategoryDialog } from "./taxonomy-edit/ChangeCategoryDialog";
import { MergeDomainDialog } from "./taxonomy-edit/MergeDomainDialog";
import { MergeSkillDialog } from "./taxonomy-edit/MergeSkillDialog";
import { MoveSkillDialog } from "./taxonomy-edit/MoveSkillDialog";
import { RemoveSkillDialog } from "./taxonomy-edit/RemoveSkillDialog";
import { RenameDomainDialog } from "./taxonomy-edit/RenameDomainDialog";
import { TaxonomyNodeMenu, type TaxonomyMenuAction } from "./taxonomy-edit/TaxonomyNodeMenu";

const DEFAULT_WIDTH = 900;

export function SkillMap({
  categoryRows,
  editCategoryRows,
  categories,
  stateOf,
  selected,
  onToggleSelect,
  onOpenSkill,
}: {
  categoryRows: CategoryRow[];
  // Full, unfiltered taxonomy used to populate edit-dialog target lists so that
  // an active map/outline filter never hides a valid move/merge destination.
  editCategoryRows?: CategoryRow[];
  categories: { slug: string; label: string; kind: "hard" | "soft" }[];
  stateOf: (kind: "skill" | "domain", key: string) => SuggestionState;
  selected: Set<string>;
  onToggleSelect: (target: SuggestionTarget) => void;
  onOpenSkill: (skill: SkillRow) => void;
}) {
  const editRows = editCategoryRows ?? categoryRows;
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);
  const layerRef = useRef<HTMLDivElement>(null);
  const zoomBehaviorRef = useRef<ReturnType<typeof zoom<SVGSVGElement, unknown>> | null>(
    null,
  );
  const [containerWidth, setContainerWidth] = useState(DEFAULT_WIDTH);
  const [view, setView] = useState<MapView>({ level: "galaxy" });
  const [menuAction, setMenuAction] = useState<TaxonomyMenuAction | null>(null);

  // The d3-zoom transform is a transient, high-frequency value: writing it to
  // React state would re-render the entire node tree on every pan/zoom frame.
  // Instead we push it straight to the two DOM nodes that consume it. React
  // never owns the `transform` attribute/style, so imperative writes survive
  // unrelated re-renders (view drill, resize, menu open).
  const applyTransform = useCallback((t: ZoomTransform) => {
    gRef.current?.setAttribute("transform", t.toString());
    if (layerRef.current) {
      layerRef.current.style.transform = `translate(${t.x}px, ${t.y}px) scale(${t.k})`;
    }
  }, []);

  useEffect(() => {
    if (!containerRef.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.max(320, Math.round(entry.contentRect.width));
      setContainerWidth(width);
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!svgRef.current) return;
    const behavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.5, 2.5])
      .on("zoom", (event) => applyTransform(event.transform));
    const svg = select(svgRef.current);
    svg.call(behavior);
    zoomBehaviorRef.current = behavior;
    return () => {
      svg.on(".zoom", null);
      zoomBehaviorRef.current = null;
    };
  }, [applyTransform]);

  const viewExists = view.level === "galaxy" || categoryRows.some((category) =>
    category.slug === (view.level === "category" ? view.slug : view.categorySlug) &&
    (view.level !== "domain" || category.domains.some((domain) => domain.id === view.domainId)),
  );
  useEffect(() => {
    if (viewExists) return;
    const reset = window.setTimeout(() => setView({ level: "galaxy" }), 0);
    return () => window.clearTimeout(reset);
  }, [viewExists]);
  const activeView = useMemo<MapView>(
    () => (viewExists ? view : { level: "galaxy" }),
    [view, viewExists],
  );
  const graph = useMemo(() => buildGraph(categoryRows, activeView), [activeView, categoryRows]);
  const dimensions = useMemo(
    () => ({
      width: containerWidth,
      height: recommendedLayoutHeight(graph.nodes, containerWidth),
    }),
    [containerWidth, graph.nodes],
  );
  const nodes = useMemo(
    () => runLayout(graph.nodes, graph.links, dimensions.width, dimensions.height, graph.rootId),
    [dimensions, graph.links, graph.nodes, graph.rootId],
  );
  // Memoized: rebuilt only when the laid-out nodes change, not on every d3-zoom
  // transform tick (which re-renders this component but leaves `nodes` intact).
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const focusedCategory = activeView.level === "galaxy" ? null : categoryRows.find((category) => category.slug === (activeView.level === "category" ? activeView.slug : activeView.categorySlug)) ?? null;
  const focusedDomain = activeView.level === "domain" ? focusedCategory?.domains.find((domain) => domain.id === activeView.domainId) ?? null : null;
  // Only consumed by the merge-skill dialog; keep the full taxonomy flat-map out
  // of the per-zoom-tick render path.
  const allSkills = useMemo(
    () => editRows.flatMap((category) => category.domains.flatMap((domain) => domain.skills)),
    [editRows],
  );

  const applyZoom = (action: "in" | "out" | "reset") => {
    if (!svgRef.current || !zoomBehaviorRef.current) return;
    if (action === "reset") applyTransform(zoomIdentity);
    // jsdom does not implement SVGAnimatedLength; the imperative reset above
    // still runs, so focus transitions stay deterministic in component tests.
    if (!svgRef.current.width?.baseVal) return;
    const svg = select(svgRef.current);
    if (action === "reset") zoomBehaviorRef.current.transform(svg, zoomIdentity);
    else zoomBehaviorRef.current.scaleBy(svg, action === "in" ? 1.25 : 0.8);
  };

  if (categoryRows.length === 0) {
    return (
      <Empty className="min-h-96 border">
        <EmptyHeader>
          <EmptyTitle>No skill domains match these filters</EmptyTitle>
          <EmptyDescription>Clear a filter or refresh clustering to restore the map.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <section aria-labelledby="skill-map-title" className="border-y bg-card">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-4 sm:px-5">
        <div>
          <h2 id="skill-map-title" className="text-sm font-semibold">
            Skill constellation
          </h2>
          <p className="mt-1 max-w-2xl text-xs text-muted-foreground">
            {focusedDomain ? `Showing ${focusedDomain.skillCount} connected skills.` : focusedCategory ? "Choose a domain to inspect its skills." : "Choose a category to explore its domains."}
          </p>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Button size="sm" variant="outline" onClick={() => setMenuAction({ type: "add-skill" })}>Add skill</Button>
          {activeView.level !== "galaxy" && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setView(parentView(activeView) ?? { level: "galaxy" });
                applyZoom("reset");
              }}
            >
              <ArrowLeftIcon data-icon="inline-start" />
              {activeView.level === "domain" ? focusedCategory?.label : "All categories"}
            </Button>
          )}
          <div className="flex gap-1" aria-label="Map zoom controls">
            <Button size="icon-sm" variant="outline" aria-label="Zoom out" onClick={() => applyZoom("out")}>
              <MinusIcon data-icon="inline-start" />
            </Button>
            <Button size="icon-sm" variant="outline" aria-label="Reset zoom" onClick={() => applyZoom("reset")}>
              <Maximize2Icon data-icon="inline-start" />
            </Button>
            <Button size="icon-sm" variant="outline" aria-label="Zoom in" onClick={() => applyZoom("in")}>
              <PlusIcon data-icon="inline-start" />
            </Button>
          </div>
        </div>
      </header>

      <div ref={containerRef} className="skill-map-grid relative overflow-hidden" style={{ height: dimensions.height }}>
        <svg
          ref={svgRef}
          className="absolute inset-0 size-full touch-none"
          role="img"
          aria-label="Domain hubs connected to expanded generalized skills"
        >
          <g ref={gRef}>
            {graph.links.map((link) => {
              const source = nodeById.get(link.source);
              const target = nodeById.get(link.target);
              if (!source || !target) return null;
              return (
                <path
                  key={`${link.source}:${link.target}`}
                  d={`M ${source.x} ${source.y} C ${(source.x + target.x) / 2} ${source.y}, ${(source.x + target.x) / 2} ${target.y}, ${target.x} ${target.y}`}
                  className="fill-none stroke-border"
                  strokeWidth="1.5"
                />
              );
            })}
          </g>
        </svg>

        <div ref={layerRef} className="pointer-events-none absolute inset-0 origin-top-left">
          {nodes.map((node) => {
            const ready = node.kind !== "category" && stateOf(node.kind, node.entityKey) === "ready";
            const target: SuggestionTarget | null = node.kind === "category" ? null : {
              kind: node.kind,
              key: node.entityKey,
              label: node.label,
            };
            const focused = graph.rootId === node.id;
            return (
              <div
                key={node.id}
                className="group pointer-events-auto absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center"
                style={{ left: node.x, top: node.y }}
              >
                <div className="relative flex items-center gap-2.5">
                  {target && <span className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-card shadow-xs">
                    <Checkbox
                      aria-label={`Select ${node.label}`}
                      checked={selected.has(targetId(target))}
                      onCheckedChange={() => onToggleSelect(target)}
                      disabled={node.kind === "domain" && node.entityKey === UNASSIGNED_ID}
                      className="size-5 bg-background"
                    />
                  </span>}
                  <Button
                    variant={node.kind === "category" ? (node.categoryKind === "hard" ? "default" : "secondary") : node.kind === "domain" ? "default" : "outline"}
                    aria-pressed={node.kind !== "skill" ? focused : undefined}
                    aria-label={
                      node.kind === "category"
                        ? `Explore ${node.label}`
                        : node.kind === "domain"
                        ? `Explore ${node.label}`
                        : `Open ${node.label} details`
                    }
                    onClick={() => {
                      if (node.kind !== "skill") {
                        setView(drillTarget(activeView, node));
                        applyZoom("reset");
                      } else if (node.skill) {
                        onOpenSkill(node.skill);
                      }
                    }}
                    className={cn(
                      "max-w-50 whitespace-normal rounded-full px-3 py-2 text-center text-xs leading-tight shadow-sm",
                      node.kind === "skill" &&
                        node.coverage === "covered" && "border-covered",
                      node.kind === "skill" &&
                        node.coverage === "adjacent" && "border-adjacent",
                      node.kind === "skill" && node.coverage === "gap" && "border-gap",
                      ready && "ring-2 ring-ready ring-offset-2 ring-offset-background",
                    )}
                    style={{ minWidth: node.radius * 2, minHeight: node.radius * 2 }}
                  >
                    {node.label}
                  </Button>
                  <TaxonomyNodeMenu
                    node={node}
                    categoryRows={editRows}
                    onAction={(action) => action.type === "open-details" ? onOpenSkill(action.skill) : setMenuAction(action)}
                    className="absolute -top-2.5 -right-2.5 z-10"
                  />
                </div>
                {(ready || (node.kind !== "skill" && Boolean(node.gapCount))) && (
                  <div className="mt-1.5 flex items-center gap-2 text-[10px] leading-none">
                    {ready && <span className="font-semibold text-ready">Ready</span>}
                    {node.kind !== "skill" && Boolean(node.gapCount) && (
                      <span className="text-muted-foreground">{node.gapCount} gaps</span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <footer className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t px-4 py-3 text-xs text-muted-foreground sm:px-5">
        <span>
          {focusedDomain ? `Focused on ${focusedDomain.label} · ${focusedDomain.skillCount} skills` : focusedCategory ? `${focusedCategory.domains.length} domains · ${focusedCategory.skillCount} skills` : `${categoryRows.length} categories · ${categoryRows.reduce((total, category) => total + category.skillCount, 0)} skills`}
        </span>
        {activeView.level === "galaxy" && <><span>● Hard</span><span>○ Soft</span></>}
        <span><i className="mr-1 inline-block size-2 rounded-full bg-primary" />Domain</span>
        <span><i className="mr-1 inline-block size-2 rounded-full bg-gap" />Gap</span>
        <span><i className="mr-1 inline-block size-2 rounded-full bg-adjacent" />Adjacent</span>
        <span><i className="mr-1 inline-block size-2 rounded-full bg-covered" />Covered</span>
        <span><i className="mr-1 inline-block size-2 rounded-full bg-ready" />Advice ready</span>
      </footer>
      {menuAction?.type === "add-skill" && <AddSkillDialog categoryRows={editRows} categories={categories} open onOpenChange={(open) => !open && setMenuAction(null)} />}
      {menuAction?.type === "move-skill" && <MoveSkillDialog skill={menuAction.skill} categoryRows={editRows} categories={categories} open onOpenChange={(open) => !open && setMenuAction(null)} />}
      {menuAction?.type === "merge-skill" && <MergeSkillDialog skill={menuAction.skill} allSkills={allSkills} open onOpenChange={(open) => !open && setMenuAction(null)} />}
      {menuAction?.type === "remove-skill" && <RemoveSkillDialog skill={menuAction.skill} open onOpenChange={(open) => !open && setMenuAction(null)} />}
      {menuAction?.type === "rename-domain" && <RenameDomainDialog domainId={menuAction.domainId} currentLabel={menuAction.label} open onOpenChange={(open) => !open && setMenuAction(null)} />}
      {menuAction?.type === "change-category" && <ChangeCategoryDialog domainId={menuAction.domainId} currentSlug={menuAction.categorySlug} categories={categories} open onOpenChange={(open) => !open && setMenuAction(null)} />}
      {menuAction?.type === "merge-domain" && <MergeDomainDialog domainId={menuAction.domainId} categoryRows={editRows} open onOpenChange={(open) => !open && setMenuAction(null)} />}
    </section>
  );
}
