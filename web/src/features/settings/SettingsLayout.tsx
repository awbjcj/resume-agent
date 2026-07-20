import { NavLink, Outlet } from "react-router-dom";
import {
  Bot,
  FileKey2,
  FileText,
  Paintbrush,
  PanelsTopLeft,
  Search,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  type LucideIcon,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

export const SETTINGS_NAV = [
  { to: "/settings/profile", label: "Profile & documents", icon: UserRound },
  { to: "/settings/search", label: "Search", icon: Search },
  { to: "/settings/sources", label: "Sources", icon: PanelsTopLeft },
  { to: "/settings/keys", label: "API keys", icon: FileKey2 },
  { to: "/settings/review", label: "Review panel", icon: Sparkles },
  { to: "/settings/agent-prompts", label: "Agent prompts", icon: Bot },
  { to: "/settings/rendering", label: "Rendering", icon: FileText },
  { to: "/settings/pruning", label: "Pruning", icon: SlidersHorizontal },
  { to: "/settings/style-guide", label: "Style guide", icon: Paintbrush },
] satisfies ReadonlyArray<{ to: string; label: string; icon: LucideIcon }>;

export function SettingsLayout() {
  return (
    <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-8">
      <aside className="lg:sticky lg:top-24 lg:w-64 lg:shrink-0">
        <Card size="sm">
          <CardHeader className="border-b">
            <CardTitle>Settings</CardTitle>
            <CardDescription>
              Shape how the workspace discovers, reviews, and renders work.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <nav aria-label="Settings">
              <ul className="flex flex-row flex-wrap gap-1.5 lg:flex-col">
                {SETTINGS_NAV.map((item) => {
                  const Icon = item.icon;
                  return (
                    <li key={item.to} className="lg:w-full">
                      <NavLink
                        to={item.to}
                        className={({ isActive }) =>
                          cn(
                            "flex min-h-10 items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:w-full",
                            isActive &&
                              "bg-primary/8 font-medium text-foreground ring-1 ring-primary/20",
                          )
                        }
                      >
                        <Icon aria-hidden="true" className="size-4 shrink-0" />
                        <span>{item.label}</span>
                      </NavLink>
                    </li>
                  );
                })}
              </ul>
            </nav>
          </CardContent>
        </Card>
      </aside>
      <main
        aria-label="Settings panel"
        className="min-w-0 flex-1 rounded-xl bg-card px-5 py-6 ring-1 ring-foreground/10 sm:px-7 sm:py-8 xl:px-9"
      >
        <Outlet />
      </main>
    </div>
  );
}
