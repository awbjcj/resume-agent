import {
  ArrowUpRight,
  FileKey2,
  PanelsTopLeft,
  Search,
  Sparkles,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";

type Shortcut = {
  to: string;
  label: string;
  detail: string;
  icon: LucideIcon;
};

const SHORTCUTS: Shortcut[] = [
  {
    to: "/settings/sources",
    label: "Sources",
    detail: "Manage job feeds",
    icon: PanelsTopLeft,
  },
  {
    to: "/settings/search",
    label: "Search settings",
    detail: "Tune discovery filters",
    icon: Search,
  },
  {
    to: "/settings/review",
    label: "Review workflow",
    detail: "Configure tailoring checks",
    icon: Sparkles,
  },
  {
    to: "/profile?tab=skills",
    label: "Profile skills",
    detail: "Tune skill groups",
    icon: Wrench,
  },
  {
    to: "/settings/keys",
    label: "API keys",
    detail: "Connect model providers",
    icon: FileKey2,
  },
];

export function QuickAccess() {
  return (
    <nav aria-label="Workspace shortcuts" className="overflow-hidden rounded-xl border bg-card">
      <div className="flex items-center justify-between gap-4 border-b bg-muted/20 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">Quick access</span>
          <span className="hidden text-xs text-muted-foreground sm:inline">Workspace controls, one click away</span>
        </div>
        <ArrowUpRight className="size-4 text-muted-foreground" aria-hidden="true" />
      </div>
      <div className="grid sm:grid-cols-2 xl:grid-cols-5">
        {SHORTCUTS.map((shortcut) => (
          <Link
            key={shortcut.to}
            to={shortcut.to}
            aria-label={`Open ${shortcut.label}: ${shortcut.detail}`}
            className={cn(
              "group flex min-h-16 items-center gap-3 px-4 py-3 outline-none transition-[background-color,color,transform] duration-150 ease-out-strong active:scale-[0.98] focus-visible:z-10 focus-visible:ring-[3px] focus-visible:ring-ring/50",
              "border-b last:border-b-0 sm:[&:nth-child(odd)]:border-r",
              "xl:border-b-0 xl:border-r xl:[&:nth-child(odd)]:border-r xl:last:border-r-0",
            )}
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background text-muted-foreground group-hover:text-foreground">
              <shortcut.icon className="size-4" aria-hidden="true" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2 text-sm font-medium">{shortcut.label}</span>
              <span className="block truncate text-xs text-muted-foreground">{shortcut.detail}</span>
            </span>
            <ArrowUpRight className="size-3.5 shrink-0 text-muted-foreground/70" aria-hidden="true" />
          </Link>
        ))}
      </div>
    </nav>
  );
}
