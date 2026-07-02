import { useEffect, useMemo, useRef, useState } from "react";
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
  UNTHEMED_ID,
  type SkillRow,
  type SuggestionState,
  type SuggestionTarget,
  type ThemeRow,
} from "./aggregate";
import {
  buildGraph,
  nextFocusedTheme,
  recommendedLayoutHeight,
  runLayout,
} from "./skill-map-layout";

const DEFAULT_WIDTH = 900;

export function SkillMap({
  themeRows,
  stateOf,
  selected,
  onToggleSelect,
  onOpenSkill,
}: {
  themeRows: ThemeRow[];
  stateOf: (kind: "skill" | "theme", key: string) => SuggestionState;
  selected: Set<string>;
  onToggleSelect: (target: SuggestionTarget) => void;
  onOpenSkill: (skill: SkillRow) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const zoomBehaviorRef = useRef<ReturnType<typeof zoom<SVGSVGElement, unknown>> | null>(
    null,
  );
  const [containerWidth, setContainerWidth] = useState(DEFAULT_WIDTH);
  const [focusedThemeId, setFocusedThemeId] = useState<string | null>(null);
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity);

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
      .on("zoom", (event) => setTransform(event.transform));
    const svg = select(svgRef.current);
    svg.call(behavior);
    zoomBehaviorRef.current = behavior;
    return () => {
      svg.on(".zoom", null);
      zoomBehaviorRef.current = null;
    };
  }, []);

  const activeFocusedThemeId = themeRows.some((theme) => theme.id === focusedThemeId)
    ? focusedThemeId
    : null;
  const graph = useMemo(
    () => buildGraph(themeRows, activeFocusedThemeId),
    [activeFocusedThemeId, themeRows],
  );
  const dimensions = useMemo(
    () => ({
      width: containerWidth,
      height: recommendedLayoutHeight(graph.nodes, containerWidth),
    }),
    [containerWidth, graph.nodes],
  );
  const nodes = useMemo(
    () => runLayout(graph.nodes, graph.links, dimensions.width, dimensions.height),
    [dimensions, graph.links, graph.nodes],
  );
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const focusedTheme = themeRows.find((theme) => theme.id === activeFocusedThemeId) ?? null;
  const transformStyle = `translate(${transform.x}px, ${transform.y}px) scale(${transform.k})`;

  const applyZoom = (action: "in" | "out" | "reset") => {
    if (!svgRef.current || !zoomBehaviorRef.current) return;
    if (action === "reset") setTransform(zoomIdentity);
    // jsdom does not implement SVGAnimatedLength; the state update above still
    // makes focus transitions deterministic in component tests.
    if (!svgRef.current.width?.baseVal) return;
    const svg = select(svgRef.current);
    if (action === "reset") zoomBehaviorRef.current.transform(svg, zoomIdentity);
    else zoomBehaviorRef.current.scaleBy(svg, action === "in" ? 1.25 : 0.8);
  };

  if (themeRows.length === 0) {
    return (
      <Empty className="min-h-96 border">
        <EmptyHeader>
          <EmptyTitle>No skill themes match these filters</EmptyTitle>
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
            {focusedTheme
              ? `Showing ${focusedTheme.skillCount} connected skills. Select a checkbox to add research.`
              : "Choose a theme to focus its branches. Select a checkbox to add research."}
          </p>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          {focusedTheme && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setFocusedThemeId(null);
                applyZoom("reset");
              }}
            >
              <ArrowLeftIcon data-icon="inline-start" />
              All themes
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
          aria-label="Theme hubs connected to expanded generalized skills"
        >
          <g transform={transform.toString()}>
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

        <div
          className="pointer-events-none absolute inset-0 origin-top-left"
          style={{ transform: transformStyle }}
        >
          {nodes.map((node) => {
            const ready = stateOf(node.kind, node.entityKey) === "ready";
            const target: SuggestionTarget = {
              kind: node.kind,
              key: node.entityKey,
              label: node.label,
            };
            const focused = node.kind === "theme" && activeFocusedThemeId === node.entityKey;
            return (
              <div
                key={node.id}
                className="pointer-events-auto absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1"
                style={{ left: node.x, top: node.y }}
              >
                <div className="relative flex items-center gap-2.5">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-md border bg-card shadow-xs">
                    <Checkbox
                      aria-label={`Select ${node.label}`}
                      checked={selected.has(targetId(target))}
                      onCheckedChange={() => onToggleSelect(target)}
                      disabled={node.kind === "theme" && node.entityKey === UNTHEMED_ID}
                      className="size-5 bg-background"
                    />
                  </span>
                  <Button
                    variant={node.kind === "theme" ? "default" : "outline"}
                    aria-pressed={node.kind === "theme" ? focused : undefined}
                    aria-label={
                      node.kind === "theme"
                        ? `${focused ? "Show all themes from" : "Focus"} ${node.label}`
                        : `Open ${node.label} details`
                    }
                    onClick={() => {
                      if (node.kind === "theme") {
                        setFocusedThemeId((current) => nextFocusedTheme(current, node.entityKey));
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
                </div>
                {ready && <span className="text-[10px] font-semibold text-ready">Ready</span>}
              </div>
            );
          })}
        </div>
      </div>

      <footer className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t px-4 py-3 text-xs text-muted-foreground sm:px-5">
        <span>
          {focusedTheme ? `Focused on ${focusedTheme.label}` : `${themeRows.length} ${themeRows.length === 1 ? "theme" : "themes"}`} ·{" "}
          {focusedTheme
            ? focusedTheme.skillCount
            : themeRows.reduce((total, theme) => total + theme.skillCount, 0)}{" "}
          skills
        </span>
        <span><i className="mr-1 inline-block size-2 rounded-full bg-primary" />Theme</span>
        <span><i className="mr-1 inline-block size-2 rounded-full bg-gap" />Gap</span>
        <span><i className="mr-1 inline-block size-2 rounded-full bg-adjacent" />Adjacent</span>
        <span><i className="mr-1 inline-block size-2 rounded-full bg-covered" />Covered</span>
        <span><i className="mr-1 inline-block size-2 rounded-full bg-ready" />Advice ready</span>
      </footer>
    </section>
  );
}
