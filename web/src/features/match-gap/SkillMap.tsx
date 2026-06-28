import { useEffect, useMemo, useRef, useState } from "react";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type ZoomTransform } from "d3-zoom";
import { Maximize2Icon, MinusIcon, PlusIcon } from "lucide-react";

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
  type SkillRow,
  type SuggestionState,
  type SuggestionTarget,
  type ThemeRow,
} from "./aggregate";
import {
  buildGraph,
  nextExpandedThemes,
  runLayout,
} from "./skill-map-layout";

const DEFAULT_SIZE = { width: 900, height: 520 };

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
  const [dimensions, setDimensions] = useState(DEFAULT_SIZE);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity);

  useEffect(() => {
    if (!containerRef.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.max(320, Math.round(entry.contentRect.width));
      setDimensions({ width, height: width < 640 ? 460 : 540 });
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

  const graph = useMemo(() => buildGraph(themeRows, expanded), [expanded, themeRows]);
  const nodes = useMemo(
    () => runLayout(graph.nodes, graph.links, dimensions.width, dimensions.height),
    [dimensions, graph.links, graph.nodes],
  );
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const transformStyle = `translate(${transform.x}px, ${transform.y}px) scale(${transform.k})`;

  const applyZoom = (action: "in" | "out" | "reset") => {
    if (!svgRef.current || !zoomBehaviorRef.current) return;
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
            Expand up to two themes. Open a skill for evidence or select it for research.
          </p>
        </div>
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
                <line
                  key={`${link.source}:${link.target}`}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  className="stroke-border"
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
            const open = node.kind === "theme" && expanded.includes(node.entityKey);
            return (
              <div
                key={node.id}
                className="pointer-events-auto absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1"
                style={{ left: node.x, top: node.y }}
              >
                <div className="relative flex items-center gap-1.5">
                  <Checkbox
                    aria-label={`Select ${node.label}`}
                    checked={selected.has(targetId(target))}
                    onCheckedChange={() => onToggleSelect(target)}
                    className="bg-background"
                  />
                  <Button
                    variant={node.kind === "theme" ? "default" : "outline"}
                    aria-label={
                      node.kind === "theme"
                        ? `${open ? "Collapse" : "Expand"} ${node.label}`
                        : `Open ${node.label} details`
                    }
                    onClick={() => {
                      if (node.kind === "theme") {
                        setExpanded((current) => nextExpandedThemes(current, node.entityKey));
                      } else if (node.skill) {
                        onOpenSkill(node.skill);
                      }
                    }}
                    className={cn(
                      "rounded-full px-3 text-xs shadow-sm",
                      node.kind === "skill" &&
                        (node.covered ? "border-covered" : "border-gap"),
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
          {themeRows.length} {themeRows.length === 1 ? "theme" : "themes"} ·{" "}
          {themeRows.reduce((total, theme) => total + theme.skillCount, 0)} skills
        </span>
        <span><i className="mr-1 inline-block size-2 rounded-full bg-primary" />Theme</span>
        <span><i className="mr-1 inline-block size-2 rounded-full bg-gap" />Gap</span>
        <span><i className="mr-1 inline-block size-2 rounded-full bg-covered" />Covered</span>
        <span><i className="mr-1 inline-block size-2 rounded-full bg-ready" />Advice ready</span>
      </footer>
    </section>
  );
}
