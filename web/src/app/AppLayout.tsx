import { NavLink, Outlet } from "react-router-dom";

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
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
import { ThemeToggle } from "@/components/ThemeToggle";

const NAV = [
  { to: "/", label: "Shortlist", end: true },
  { to: "/pipeline", label: "Pipeline" },
  { to: "/triage", label: "Triage" },
  { to: "/analytics", label: "Analytics" },
  { to: "/match-gap", label: "Match-gap" },
];

export function AppLayout() {
  return (
    <SidebarProvider>
      <Sidebar>
        <SidebarHeader className="p-4">
          <div className="font-mono text-xs uppercase tracking-[0.3em] text-primary">
            Resume Agent
          </div>
          <div className="font-serif text-2xl font-bold leading-tight">The Broadsheet</div>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                {NAV.map((n) => (
                  <SidebarMenuItem key={n.to}>
                    {/* base-ui render prop keeps a single interactive element (the
                        NavLink); NavLink sets aria-current="page" when active. */}
                    <SidebarMenuButton
                      render={
                        <NavLink to={n.to} end={n.end}>
                          {n.label}
                        </NavLink>
                      }
                    />
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
      </Sidebar>
      <SidebarInset>
        <header className="flex items-center gap-3 border-b px-6 py-3">
          <SidebarTrigger className="md:hidden" />
          <RunActions />
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </header>
        <RunPanel />
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
