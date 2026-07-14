import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Plus } from "lucide-react";
import { toast } from "sonner";

import {
  Alert,
  AlertAction,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";

export function PersonalTokensCard() {
  const queryClient = useQueryClient();
  const tokens = useQuery({
    queryKey: ["account", "tokens"],
    queryFn: () => unwrap(api.GET("/api/account/tokens")),
  });
  const [tokenName, setTokenName] = useState("");
  const [newToken, setNewToken] = useState<string | null>(null);
  const createToken = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/account/tokens", { body: { name: tokenName } })),
    onSuccess: (created) => {
      setNewToken(created.token);
      setTokenName("");
      void queryClient.invalidateQueries({ queryKey: ["account", "tokens"] });
    },
  });

  if (tokens.isPending) return <Skeleton className="h-72 w-full" />;
  if (tokens.isError || !tokens.data) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Access tokens are unavailable</AlertTitle>
        <AlertDescription>{tokens.error?.message ?? "Please try again."}</AlertDescription>
      </Alert>
    );
  }

  return (
    <form
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        createToken.mutate();
      }}
    >
      <Card>
        <CardHeader className="border-b">
          <div className="flex items-start gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
              <KeyRound aria-hidden="true" />
            </div>
            <div className="flex flex-col gap-1">
              <CardTitle>
                <h3>Personal access tokens</h3>
              </CardTitle>
              <CardDescription>
                Create named credentials for scripts and local automation. New tokens are shown once.
              </CardDescription>
            </div>
          </div>
          <CardAction>
            <Badge variant="secondary">{tokens.data.tokens.length} active</Badge>
          </CardAction>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="token-name">Token name</FieldLabel>
              <Input
                id="token-name"
                value={tokenName}
                placeholder="Local automation"
                onChange={(event) => setTokenName(event.target.value)}
                required
              />
            </Field>
          </FieldGroup>
          {newToken ? (
            <Alert>
              <KeyRound aria-hidden="true" />
              <AlertTitle>Copy this token now</AlertTitle>
              <AlertDescription>
                <code className="block break-all font-mono text-xs">{newToken}</code>
              </AlertDescription>
              <AlertAction>
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  aria-label="Copy new token"
                  onClick={() => {
                    void navigator.clipboard.writeText(newToken);
                    toast.success("Token copied");
                  }}
                >
                  <Copy aria-hidden="true" />
                </Button>
              </AlertAction>
            </Alert>
          ) : null}
          {tokens.data.tokens.length ? (
            <ul className="flex flex-col divide-y rounded-lg border">
              {tokens.data.tokens.map((token) => (
                <li className="flex items-center gap-3 px-4 py-3.5 text-sm" key={token.id}>
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted">
                    <KeyRound aria-hidden="true" />
                  </div>
                  <span className="min-w-0 flex-1 truncate font-medium">{token.name}</span>
                  <time className="shrink-0 text-xs text-muted-foreground" dateTime={token.createdAt}>
                    {new Date(token.createdAt).toLocaleDateString()}
                  </time>
                </li>
              ))}
            </ul>
          ) : (
            <Empty className="border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <KeyRound aria-hidden="true" />
                </EmptyMedia>
                <EmptyTitle>No access tokens</EmptyTitle>
                <EmptyDescription>
                  Name your first token above to connect an automation.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </CardContent>
        <CardFooter className="justify-between gap-3">
          <p className="text-xs text-muted-foreground">Treat tokens like passwords.</p>
          <Button type="submit" disabled={createToken.isPending}>
            {createToken.isPending ? (
              <Spinner data-icon="inline-start" />
            ) : (
              <Plus data-icon="inline-start" />
            )}
            Create token
          </Button>
        </CardFooter>
      </Card>
    </form>
  );
}
