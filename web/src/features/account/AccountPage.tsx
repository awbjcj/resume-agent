import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, KeyRound, Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Progress, ProgressLabel, ProgressValue } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { api, openDownload, unwrap } from "@/lib/api/client";
import { useMe } from "@/features/auth/AuthGate";

export function AccountPage() {
  const me = useMe();
  const queryClient = useQueryClient();
  const usage = useQuery({ queryKey: ["account", "usage"], queryFn: () => unwrap(api.GET("/api/account/usage")) });
  const tokens = useQuery({ queryKey: ["account", "tokens"], queryFn: () => unwrap(api.GET("/api/account/tokens")) });
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [tokenName, setTokenName] = useState("");
  const [newToken, setNewToken] = useState<string | null>(null);
  const password = useMutation({
    mutationFn: () => unwrap(api.POST("/api/account/password", { body: { currentPassword, newPassword } })),
    onSuccess: () => { setCurrentPassword(""); setNewPassword(""); },
  });
  const createToken = useMutation({
    mutationFn: () => unwrap(api.POST("/api/account/tokens", { body: { name: tokenName } })),
    onSuccess: (created) => {
      setNewToken(created.token);
      setTokenName("");
      void queryClient.invalidateQueries({ queryKey: ["account", "tokens"] });
    },
  });

  if (!me.data || !usage.data || !tokens.data) return <Skeleton className="h-80 w-full" />;
  const percent = usage.data.budget === 0 ? 0 : Math.min(100, usage.data.weightedTotal / usage.data.budget * 100);
  return (
    <div className="flex flex-col gap-6">
      <header>
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Personal workspace</p>
        <h1 className="mt-1 text-2xl font-semibold">Account</h1>
        <p className="text-sm text-muted-foreground">Signed in as {me.data.username} <Badge variant="outline">{me.data.role ?? "user"}</Badge></p>
      </header>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Weekly usage</CardTitle><CardDescription>Own-key calls are recorded but do not count against the shared budget.</CardDescription></CardHeader>
          <CardContent className="space-y-4">
            <Progress value={percent}><ProgressLabel>Shared budget</ProgressLabel><ProgressValue>{() => `${usage.data.weightedTotal.toLocaleString()} / ${usage.data.budget === 0 ? "Unlimited" : usage.data.budget.toLocaleString()}`}</ProgressValue></Progress>
            <p className="text-sm text-muted-foreground">Own-key weighted tokens: {usage.data.ownKeyWeightedTotal.toLocaleString()}</p>
            <Button variant="outline" render={<a href="/api/account/export" onClick={(event) => { event.preventDefault(); void openDownload(event.currentTarget.href); }}><Download aria-hidden="true" />Export workspace</a>} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Change password</CardTitle><CardDescription>Changing it immediately invalidates your other sessions.</CardDescription></CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={(event: FormEvent) => { event.preventDefault(); password.mutate(); }}>
              <FieldGroup>
                <Field><FieldLabel htmlFor="current-password">Current password</FieldLabel><Input id="current-password" type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required /></Field>
                <Field data-invalid={password.isError || undefined}><FieldLabel htmlFor="new-password">New password</FieldLabel><Input id="new-password" type="password" autoComplete="new-password" minLength={12} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required />{password.isError && <FieldError>{password.error.message}</FieldError>}</Field>
              </FieldGroup>
              <Button type="submit" disabled={password.isPending}><KeyRound aria-hidden="true" />Update password</Button>
            </form>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader><CardTitle>Personal access tokens</CardTitle><CardDescription>Use PATs for automation. A token is shown once when created.</CardDescription></CardHeader>
        <CardContent className="space-y-4">
          <form className="flex flex-col gap-3 sm:flex-row" onSubmit={(event) => { event.preventDefault(); createToken.mutate(); }}>
            <Field className="flex-1"><FieldLabel htmlFor="token-name">Token name</FieldLabel><Input id="token-name" value={tokenName} onChange={(event) => setTokenName(event.target.value)} required /></Field>
            <Button className="sm:self-end" type="submit" disabled={createToken.isPending}><Plus aria-hidden="true" />Create token</Button>
          </form>
          {newToken && <div role="status" className="rounded-lg border border-primary/30 bg-primary/5 p-3 font-mono text-sm break-all">{newToken}</div>}
          <ul className="divide-y rounded-lg border">{tokens.data.tokens.map((token) => <li className="flex justify-between gap-4 p-3 text-sm" key={token.id}><span>{token.name}</span><span className="text-muted-foreground">{new Date(token.createdAt).toLocaleDateString()}</span></li>)}</ul>
        </CardContent>
      </Card>
    </div>
  );
}
