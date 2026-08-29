import { NavLink, Outlet } from "react-router-dom";
import {
  BarChart3,
  Briefcase,
  Inbox,
  Kanban,
  LayoutDashboard,
  MessageCircleMore,
  MessagesSquare,
  Settings,
  CircleUserRound,
  ShieldCheck,
  Banknote,
  Network,
  Compass,
  Sparkles,
  Target,
  UserRound,
  type LucideIcon,
} from "lucide-react";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import { RunActions } from "@/features/runs/RunActions";
import { ActiveInterviewBanner } from "@/features/interview/ActiveInterviewBanner";
import { useInterviewSessions } from "@/features/interview/use-interview";
import { RunPanel } from "@/features/runs/RunPanel";
import { useRehydrateRuns } from "@/features/runs/use-rehydrate-runs";
import { useRunCompletionEffects } from "@/features/runs/use-run-completion-effects";
import { ThemeToggle } from "@/components/ThemeToggle";
import { NotificationsBell } from "@/features/notifications/NotificationsBell";
import { LogoutButton } from "@/features/auth/LogoutButton";
import { useMe } from "@/features/auth/AuthGate";

type NavItem = { to: string; label: string; end?: boolean; icon: LucideIcon };

// The main nav mirrors the job-hunting arc: prepare your profile, work the
// funnel in its true order (new jobs → picks → tailoring), then analyse.
// Dashboard stands alone as the home/overview.
const NAV_GROUPS: { label?: string; items: NavItem[] }[] = [
  {
    items: [{ to: "/", label: "Dashboard", end: true, icon: LayoutDashboard }],
  },
  {
    label: "Prepare",
    items: [
      { to: "/profile", label: "Profile", icon: UserRound },
      { to: "/coach", label: "Profile coach", icon: MessageCircleMore },
      { to: "/interview", label: "Mock interviews", icon: MessagesSquare },
      { to: "/career-lab", label: "Career Lab", icon: Sparkles },
    ],
  },
  {
    label: "Find & tailor",
    items: [
      { to: "/scout", label: "Discovery Scout", icon: Compass },
      { to: "/triage", label: "Triage", icon: Inbox },
      { to: "/shortlist", label: "Shortlist", icon: Briefcase },
      { to: "/pipeline", label: "Pipeline", icon: Kanban },
    ],
  },
  {
    label: "Insight",
    items: [
      { to: "/match-gap", label: "Match-gap", icon: Target },
      { to: "/analytics", label: "Analytics", icon: BarChart3 },
    ],
  },
];

function NavMenuItem({ item, badge }: { item: NavItem; badge?: number }) {
  // base-ui render prop keeps a single interactive element (the NavLink);
  // NavLink sets aria-current="page" when active.
  const badged = Boolean(badge);
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        className={cn(
          "h-10 rounded-lg px-3 text-[0.95rem] transition-[background-color,color,box-shadow,transform] duration-150 ease-out-strong active:scale-[0.98] motion-reduce:transform-none",
          badged && "pr-9",
        )}
        render={
          <NavLink to={item.to} end={item.end}>
            <item.icon className="size-4" aria-hidden="true" />
            <span>{item.label}</span>
          </NavLink>
        }
      />
      {badged ? (
        // The badge's own `peer-data-[size=default]:top-1.5` assumes an h-8
        // button; ours is h-10, so centre it — `!` is needed to outrank that
        // higher-specificity variant.
        <SidebarMenuBadge className="top-1/2! -translate-y-1/2 bg-primary/15 text-primary">
          {badge}
          <span className="sr-only"> in progress</span>
        </SidebarMenuBadge>
      ) : null}
    </SidebarMenuItem>
  );
}

export function AppLayout() {
  // Registered before the first reconciliation so a completion recovered on
  // load cannot be dispatched to an empty listener set.
  useRunCompletionEffects();
  useRehydrateRuns();
  const me = useMe();
  // Shares the cached query the interview banner already runs, so the nav count
  // costs no extra request.
  const interviewSessions = useInterviewSessions();
  const navBadges: Record<string, number> = {
    "/interview": (interviewSessions.data?.sessions ?? []).filter(
      (session) => session.status === "active",
    ).length,
  };
  return (
    <SidebarProvider className="command-shell">
      <Sidebar className="border-r border-sidebar-border/80 bg-sidebar">
        <div className="command-panel flex min-h-0 flex-1 flex-col">
          <SidebarHeader className="relative gap-5 border-b border-sidebar-border/70 p-5 pb-4">
            <div className="flex items-center gap-3">
              <div className="command-panel-mark flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
                <Sparkles className="size-4.5" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <div className="text-[0.65rem] font-semibold uppercase tracking-[0.28em] text-primary">
                  Resume Agent
                </div>
                <div className="mt-0.5 text-lg font-semibold leading-tight tracking-[-0.025em]">
                  Command Center
                </div>
              </div>
            </div>

            <div className="command-sidebar-brief rounded-xl border border-sidebar-border/80 p-3.5">
              <div className="flex items-center gap-2 text-[0.64rem] font-semibold uppercase tracking-[0.18em] text-sidebar-foreground/55">
                <Target className="size-3.5 text-sidebar-primary" aria-hidden="true" />
                Operational flow
              </div>
              <p className="mt-2 text-xs leading-relaxed text-sidebar-foreground/72">
                Move each strong fit from evidence to a finished application.
              </p>
              <div className="mt-3 flex items-center gap-1.5 text-[0.66rem] font-medium text-sidebar-foreground/65">
                <span>Review</span>
                <span className="h-px flex-1 bg-sidebar-border" />
                <span>Tailor</span>
                <span className="h-px flex-1 bg-sidebar-border" />
                <span>Track</span>
              </div>
            </div>
          </SidebarHeader>
          <SidebarContent className="py-2">
            {NAV_GROUPS.map((group, i) => (
              <SidebarGroup key={group.label ?? `group-${i}`} className="px-3">
                {group.label && (
                  <SidebarGroupLabel className="px-3 text-[0.65rem] font-semibold uppercase tracking-[0.2em] text-sidebar-foreground/48">
                    {group.label}
                  </SidebarGroupLabel>
                )}
                <SidebarGroupContent>
                  <SidebarMenu className="gap-1">
                    {group.items.map((item) => (
                      <NavMenuItem key={item.to} item={item} badge={navBadges[item.to]} />
                    ))}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            ))}
            <SidebarGroup className="mt-auto px-3">
              <SidebarGroupLabel className="px-3 text-[0.65rem] font-semibold uppercase tracking-[0.2em] text-sidebar-foreground/48">
                Workspace
              </SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu className="gap-1">
                  <NavMenuItem item={{ to: "/settings", label: "Settings", icon: Settings }} />
                  <NavMenuItem item={{ to: "/account", label: "Account", icon: CircleUserRound }} />
                  {me.data?.role === "admin" && (
                    <>
                      <NavMenuItem item={{ to: "/admin", label: "Admin", end: true, icon: ShieldCheck }} />
                      <NavMenuItem item={{ to: "/admin/quotas", label: "Cost quotas", icon: Banknote }} />
                      <NavMenuItem item={{ to: "/admin/routing", label: "Provider routing", icon: Network }} />
                    </>
                  )}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>
          <SidebarFooter className="border-t border-sidebar-border/70 p-4">
            <div className="rounded-xl border border-sidebar-border/80 bg-sidebar/72 p-3.5 shadow-[inset_0_1px_0_color-mix(in_oklab,var(--sidebar-foreground),transparent_94%)]">
              <div className="flex items-center gap-2 text-sm font-medium">
                <span className="size-1.5 rounded-full bg-ready shadow-[0_0_0_4px_color-mix(in_oklab,var(--ready),transparent_86%)]" />
                Daily focus
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-sidebar-foreground/66">
                Approve the best fits first, then run tailoring in batches.
              </p>
            </div>
          </SidebarFooter>
        </div>
      </Sidebar>
      <SidebarInset>
        {/* `app-chrome` is the hook that makes this translucent layer become an
            opaque surface under prefers-reduced-transparency / prefers-contrast
            (see index.css) — blur is a material here, not decoration. */}
        <header className="app-chrome sticky top-0 z-10 border-b bg-background/88 backdrop-blur-md">
          <div className="flex min-h-16 items-center gap-3 px-5 py-3 md:px-8 lg:px-10">
            <SidebarTrigger className="md:hidden" />
            <div className="flex min-w-0 items-center gap-2.5 md:hidden">
              <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
                <Sparkles className="size-4" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold leading-tight">Resume Agent</div>
                <div className="truncate text-[0.68rem] text-muted-foreground">Command Center</div>
              </div>
            </div>
            <div className="hidden min-w-0 md:block">
              <div className="text-sm font-medium">Job search operations</div>
              <div className="text-xs text-muted-foreground">Pull, discover, review, and ship.</div>
            </div>
            <RunActions className="ml-auto hidden flex-nowrap xl:flex" />
            <div className="ml-auto flex shrink-0 items-center gap-1 xl:ml-0">
              <NotificationsBell />
              <ThemeToggle />
              <LogoutButton />
            </div>
          </div>
          <div className="shell-action-rail border-t border-border/70 px-5 py-2 xl:hidden md:px-8 lg:px-10">
            <RunActions className="w-max flex-nowrap justify-start" />
          </div>
        </header>
        <RunPanel />
        <ActiveInterviewBanner />
        <main className="flex-1 px-4 py-5 sm:px-5 sm:py-6 md:px-8 lg:px-10 2xl:px-12">
          <div className="mx-auto w-full max-w-[1680px]">
            <Outlet />
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
