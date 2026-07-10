import { NavLink, Outlet } from "react-router-dom";
import {
  BarChart3,
  Briefcase,
  Inbox,
  Kanban,
  LayoutDashboard,
  Settings,
  Sparkles,
  Target,
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
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { RunActions } from "@/features/runs/RunActions";
import { RunPanel } from "@/features/runs/RunPanel";
import { useRehydrateRuns } from "@/features/runs/use-rehydrate-runs";
import { ThemeToggle } from "@/components/ThemeToggle";
import { NotificationsBell } from "@/features/notifications/NotificationsBell";
import { LogoutButton } from "@/features/auth/LogoutButton";

const NAV: { to: string; label: string; end?: boolean; icon: LucideIcon }[] = [
  { to: "/", label: "Dashboard", end: true, icon: LayoutDashboard },
  { to: "/shortlist", label: "Shortlist", icon: Briefcase },
  { to: "/pipeline", label: "Pipeline", icon: Kanban },
  { to: "/triage", label: "Triage", icon: Inbox },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/match-gap", label: "Match-gap", icon: Target },
];

export function AppLayout() {
  useRehydrateRuns();
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
          <SidebarGroup className="px-3">
            <SidebarGroupLabel className="px-3 text-[0.68rem] font-semibold uppercase tracking-[0.18em]">
              Workflows
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-1">
                {NAV.map((n) => (
                  <SidebarMenuItem key={n.to}>
                    {/* base-ui render prop keeps a single interactive element (the
                        NavLink); NavLink sets aria-current="page" when active. */}
                    <SidebarMenuButton
                      className="h-10 rounded-lg px-3 text-[0.95rem]"
                      render={
                        <NavLink to={n.to} end={n.end}>
                          <n.icon className="size-4" aria-hidden="true" />
                          <span>{n.label}</span>
                        </NavLink>
                      }
                    />
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
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
        <header className="sticky top-0 z-10 flex min-h-16 flex-wrap items-center gap-3 border-b bg-background/88 px-5 py-3 backdrop-blur md:px-8 lg:px-10">
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
        <main className="flex-1 px-5 py-6 md:px-8 lg:px-10 2xl:px-12">
          <div className="mx-auto w-full max-w-[1680px]">
            <Outlet />
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
