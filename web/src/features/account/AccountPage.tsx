import { useQuery } from "@tanstack/react-query";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/PageHeader";
import { useMe } from "@/features/auth/AuthGate";
import { api, unwrap } from "@/lib/api/client";
import { AccountUsageCard } from "./AccountUsageCard";
import { DataArchiveCard } from "./DataArchiveCard";
import { DangerZoneCard } from "./DangerZoneCard";
import { PasswordCard } from "./PasswordCard";
import { PersonalTokensCard } from "./PersonalTokensCard";

export function AccountPage() {
  const me = useMe();
  const usage = useQuery({
    queryKey: ["account", "usage"],
    queryFn: () => unwrap(api.GET("/api/account/usage")),
  });

  if (!me.data || usage.isPending) return <Skeleton className="h-80 w-full" />;
  if (usage.isError || !usage.data) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Account details are unavailable</AlertTitle>
        <AlertDescription>{usage.error?.message ?? "Please try again."}</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        kicker="Personal workspace"
        title="Account"
        sub={`Signed in as ${me.data.username}. Manage credentials, automation access, and the data held in your workspace.`}
      />
      <div className="-mt-5 flex items-center gap-2 text-sm text-muted-foreground">
        <span>Access level</span>
        <Badge variant={me.data.role === "admin" ? "default" : "outline"}>
          {me.data.role ?? "user"}
        </Badge>
      </div>

      <section aria-labelledby="account-security" className="flex flex-col gap-4">
        <div>
          <h2 id="account-security" className="text-lg font-semibold">
            Security and access
          </h2>
          <p className="text-sm text-muted-foreground">
            Review usage, update sign-in credentials, and issue automation tokens.
          </p>
        </div>
        <div className="grid gap-6 xl:grid-cols-2">
          <AccountUsageCard usage={usage.data} isAdmin={me.data.role === "admin"} />
          <PasswordCard />
        </div>
        <PersonalTokensCard />
      </section>

      <section aria-labelledby="account-data" className="flex flex-col gap-4">
        <div>
          <h2 id="account-data" className="text-lg font-semibold">
            Workspace data
          </h2>
          <p className="text-sm text-muted-foreground">
            Keep a portable archive or remove data at a clearly defined scope.
          </p>
        </div>
        <DataArchiveCard
          title="My workspace data"
          description="Export your workspace for a local browser pull, then import it back without touching anyone else's data. The archive contains operational secrets."
          exportLabel="Export my data"
          exportPath="/api/account/export"
          importPath="/api/account/import"
          successMessage="Workspace imported"
        />
        <DangerZoneCard />
      </section>
    </div>
  );
}
