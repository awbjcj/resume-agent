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
        className={cn("h-10 rounded-lg px-3 text-[0.95rem]", badged && "pr-9")}
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
    <SidebarProvider>
      <Sidebar className="border-r border-sidebar-border/80 bg-sidebar/95">
        <SidebarHeader className="gap-4 p-5">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
              <Sparkles className="size-5" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <div className="text-[0.68rem] font-semibold uppercase tracking-[0.28em] text-primary">
                Resume Agent
              </div>
              <div className="text-lg font-semibold leading-tight">Command Center</div>
            </div>
          </div>
          <div className="rounded-lg border border-sidebar-border bg-sidebar-accent/55 p-3 text-xs leading-relaxed text-sidebar-foreground/75">
            Review, tailor, and track high-fit jobs from one operational desk.
          </div>
        </SidebarHeader>
        <SidebarContent>
          {NAV_GROUPS.map((group, i) => (
            <SidebarGroup key={group.label ?? `group-${i}`} className="px-3">
              {group.label && (
                <SidebarGroupLabel className="px-3 text-[0.68rem] font-semibold uppercase tracking-[0.18em]">
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
            <SidebarGroupLabel className="px-3 text-[0.68rem] font-semibold uppercase tracking-[0.18em]">
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
                  </>
                )}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="p-5">
          <div className="rounded-lg border border-sidebar-border p-3">
            <div className="text-sm font-medium">Daily focus</div>
            <p className="mt-1 text-xs leading-relaxed text-sidebar-foreground/70">
              Approve the best fits first, then run tailoring in batches.
            </p>
          </div>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        {/* `app-chrome` is the hook that makes this translucent layer become an
            opaque surface under prefers-reduced-transparency / prefers-contrast
            (see index.css) — blur is a material here, not decoration. */}
        <header className="app-chrome sticky top-0 z-10 flex min-h-16 flex-wrap items-center gap-3 border-b bg-background/88 px-5 py-3 backdrop-blur-md md:px-8 lg:px-10">
          <SidebarTrigger className="md:hidden" />
          <div className="hidden min-w-0 md:block">
            <div className="text-sm font-medium">Job search operations</div>
            <div className="text-xs text-muted-foreground">Pull, discover, review, and ship.</div>
          </div>
          <div className="ml-auto flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2">
            <RunActions />
            <NotificationsBell />
            <ThemeToggle />
            <LogoutButton />
          </div>
        </header>
        <RunPanel />
        <ActiveInterviewBanner />
        <main className="flex-1 px-5 py-6 md:px-8 lg:px-10 2xl:px-12">
          <div className="mx-auto w-full max-w-[1680px]">
            <Outlet />
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
