import { ShieldCheck } from "lucide-react";
import { Navigate } from "react-router-dom";
import { Link } from "react-router-dom";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { DataArchiveCard } from "@/features/account/DataArchiveCard";
import { useMe } from "@/features/auth/AuthGate";
import { AdminInviteCard } from "./AdminInviteCard";
import { AdminLimitsCard } from "./AdminLimitsCard";
import { AdminUsersCard } from "./AdminUsersCard";
import { MailWarning } from "./MailWarning";

export function AdminPage() {
  const me = useMe();

  if (me.isPending) return <Skeleton className="h-80 w-full" />;
  if (me.data?.role !== "admin") return <Navigate to="/" replace />;

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        kicker="Workspace governance"
        title="Administration"
        sub="Manage member access, operational limits, invitation codes, and complete system backups."
      />
      <nav aria-label="Administration sections" className="-mt-5 flex gap-2">
        <Button variant="secondary" size="sm">Access &amp; data</Button>
        <Button nativeButton={false} variant="outline" size="sm" render={<Link to="/admin/quotas" />}>Cost quotas</Button>
        <Button nativeButton={false} variant="outline" size="sm" render={<Link to="/admin/routing" />}>Provider routing</Button>
      </nav>
      <Alert className="-mt-5">
        <ShieldCheck aria-hidden="true" />
        <AlertTitle>Administrator access is unlimited</AlertTitle>
        <AlertDescription>
          Cost allowances, active-job caps, and maximum concurrency do not apply to
          administrators. Their shared-key spend still counts against the platform cap.
        </AlertDescription>
      </Alert>
      <MailWarning />

      <section aria-labelledby="admin-controls" className="flex flex-col gap-4">
        <div>
          <h2 id="admin-controls" className="text-lg font-semibold">
            Access and capacity
          </h2>
          <p className="text-sm text-muted-foreground">
            Invite new members and set comfortable operating limits for their workspaces.
          </p>
        </div>
        <div className="grid gap-6 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.4fr)]">
          <AdminInviteCard />
          <AdminLimitsCard />
        </div>
      </section>

      <section aria-labelledby="admin-data" className="flex flex-col gap-4">
        <div>
          <h2 id="admin-data" className="text-lg font-semibold">
            System data
          </h2>
          <p className="text-sm text-muted-foreground">
            Keep a complete portable snapshot before maintenance or migration.
          </p>
        </div>
        <DataArchiveCard
          title="System backup"
          description="Export or replace the complete server data root, including every workspace."
          exportLabel="Export all data"
          exportPath="/api/admin/export"
          importPath="/api/admin/import"
          successMessage="Data imported"
        />
      </section>

      <section aria-labelledby="admin-members" className="flex flex-col gap-4">
        <div>
          <h2 id="admin-members" className="text-lg font-semibold">
            Members
          </h2>
          <p className="text-sm text-muted-foreground">
            Authorization is enforced by protected admin endpoints behind every action.
          </p>
        </div>
        <AdminUsersCard currentUsername={me.data.username ?? ""} />
      </section>
    </div>
  );
}
