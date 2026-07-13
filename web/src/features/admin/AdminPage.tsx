import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Shield, Trash2, UserRoundCog } from "lucide-react";
import { Navigate } from "react-router-dom";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useMe } from "@/features/auth/AuthGate";
import { api, unwrap } from "@/lib/api/client";
import { DataArchiveCard } from "@/features/account/DataArchiveCard";

export function AdminPage() {
  const me = useMe();
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => unwrap(api.GET("/api/admin/users")), enabled: me.data?.role === "admin" });
  const defaults = useQuery({ queryKey: ["admin", "defaults"], queryFn: () => unwrap(api.GET("/api/admin/system/defaults")), enabled: me.data?.role === "admin" });
  const [invite, setInvite] = useState<string | null>(null);
  const [draftDefaults, setDraftDefaults] = useState<{ weeklyTokenBudget: number; maxActiveJobs: number; maxConcurrentRuns: number } | null>(null);
  const invalidateUsers = () => queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
  const patch = useMutation({ mutationFn: ({ id, body }: { id: string; body: { role?: string; disabled?: boolean } }) => unwrap(api.PATCH("/api/admin/users/{user_id}", { params: { path: { user_id: id } }, body })), onSuccess: invalidateUsers });
  const remove = useMutation({ mutationFn: (id: string) => unwrap(api.DELETE("/api/admin/users/{user_id}", { params: { path: { user_id: id }, query: { confirm: "DELETE" } } })), onSuccess: invalidateUsers });
  const mintInvite = useMutation({ mutationFn: () => unwrap(api.POST("/api/admin/invites", { body: { expiresInDays: 14 } })), onSuccess: (result) => setInvite(result.code) });
  const saveDefaults = useMutation({ mutationFn: (body: { weeklyTokenBudget: number; maxActiveJobs: number; maxConcurrentRuns: number }) => unwrap(api.PUT("/api/admin/system/defaults", { body })), onSuccess: (result) => { setDraftDefaults(result); void queryClient.invalidateQueries({ queryKey: ["admin", "defaults"] }); } });

  if (me.isPending) return <Skeleton className="h-80 w-full" />;
  if (me.data?.role !== "admin") return <Navigate to="/" replace />;
  if (!users.data || !defaults.data) return <Skeleton className="h-80 w-full" />;
  const limits = draftDefaults ?? defaults.data;
  return (
    <div className="flex flex-col gap-6">
      <header><p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Access control</p><h1 className="mt-1 text-2xl font-semibold">Administration</h1><p className="text-sm text-muted-foreground">Manage identities, workspace limits, and invitation access.</p></header>
      <div className="grid gap-6 xl:grid-cols-[1fr_1.4fr]">
        <Card>
          <CardHeader><CardTitle>Invite a teammate</CardTitle><CardDescription>Invitation codes expire after 14 days and can be used once.</CardDescription></CardHeader>
          <CardContent className="space-y-4">
            <Button onClick={() => mintInvite.mutate()} disabled={mintInvite.isPending}><UserRoundCog aria-hidden="true" />Create invite</Button>
            {invite && <div className="flex items-start gap-2 rounded-lg border border-primary/30 bg-primary/5 p-3"><code className="min-w-0 flex-1 break-all text-sm">{invite}</code><Button size="icon-sm" variant="ghost" aria-label="Copy invite code" onClick={() => void navigator.clipboard.writeText(invite)}><Copy aria-hidden="true" /></Button></div>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>System defaults</CardTitle><CardDescription>Zero means unlimited. User-specific overrides take precedence.</CardDescription></CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-3">
            {([['weeklyTokenBudget', 'Weekly tokens'], ['maxActiveJobs', 'Active jobs'], ['maxConcurrentRuns', 'Concurrent runs']] as const).map(([key, label]) => <label className="space-y-1 text-sm" key={key}><span>{label}</span><Input type="number" min={0} value={limits[key]} onChange={(event) => setDraftDefaults({ ...limits, [key]: Number(event.target.value) })} /></label>)}
            <Button className="sm:col-span-3 sm:justify-self-start" onClick={() => saveDefaults.mutate(limits)} disabled={saveDefaults.isPending}><Shield aria-hidden="true" />Save defaults</Button>
          </CardContent>
        </Card>
      </div>
      <DataArchiveCard
        title="System backup"
        description="Export or replace the complete server data root, including every workspace."
        exportLabel="Export all data"
        exportPath="/api/admin/export"
        importPath="/api/admin/import"
        successMessage="Data imported"
      />
      <Card>
        <CardHeader><CardTitle>Users</CardTitle><CardDescription>Authorization is enforced by the API; these controls only call protected admin endpoints.</CardDescription></CardHeader>
        <CardContent>
          <Table><TableHeader><TableRow><TableHead>User</TableHead><TableHead>Role</TableHead><TableHead>Usage</TableHead><TableHead>Jobs</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader><TableBody>
            {users.data.users.map((user) => <TableRow key={user.id}><TableCell><div className="font-medium">{user.username}</div>{user.disabledAt && <Badge variant="destructive">Disabled</Badge>}</TableCell><TableCell><Badge variant="outline">{user.role}</Badge></TableCell><TableCell className="tabular-nums">{user.weeklyUsage.toLocaleString()}</TableCell><TableCell>{user.activeJobs}</TableCell><TableCell><div className="flex justify-end gap-2"><Button size="sm" variant="outline" onClick={() => patch.mutate({ id: user.id, body: { role: user.role === "admin" ? "user" : "admin" } })}>{user.role === "admin" ? "Make user" : "Make admin"}</Button><Button size="sm" variant="outline" onClick={() => patch.mutate({ id: user.id, body: { disabled: !user.disabledAt } })}>{user.disabledAt ? "Enable" : "Disable"}</Button><ConfirmDialog trigger={<Button size="icon-sm" variant="ghost" aria-label={`Delete ${user.username}`}><Trash2 aria-hidden="true" /></Button>} title={`Delete ${user.username}?`} description="This permanently removes the user and their workspace." confirmLabel="Delete" onConfirm={async () => { await remove.mutateAsync(user.id); }} /></div></TableCell></TableRow>)}
          </TableBody></Table>
        </CardContent>
      </Card>
    </div>
  );
}
