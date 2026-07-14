import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Copy, TicketCheck, UserRoundPlus } from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";

export function AdminInviteCard() {
  const [invite, setInvite] = useState<string | null>(null);
  const mintInvite = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/admin/invites", { body: { expiresInDays: 14 } })),
    onSuccess: (result) => setInvite(result.code),
  });

  return (
    <Card className="h-full">
      <CardHeader className="border-b">
        <div className="flex items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
            <UserRoundPlus aria-hidden="true" />
          </div>
          <div className="flex flex-col gap-1">
            <CardTitle>
              <h3>Invite a teammate</h3>
            </CardTitle>
            <CardDescription>
              Mint a single-use code for a new member account.
            </CardDescription>
          </div>
        </div>
        <CardAction>
          <Badge variant="outline">14 days</Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        {invite ? (
          <div className="flex items-center gap-2 rounded-lg border bg-muted/45 p-3">
            <code className="min-w-0 flex-1 break-all text-sm">{invite}</code>
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label="Copy invite code"
              onClick={() => {
                void navigator.clipboard.writeText(invite);
                toast.success("Invite code copied");
              }}
            >
              <Copy aria-hidden="true" />
            </Button>
          </div>
        ) : (
          <p className="text-sm leading-6 text-muted-foreground">
            Codes expire automatically and cannot be reused after registration.
          </p>
        )}
        {mintInvite.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Invite could not be created</AlertTitle>
            <AlertDescription>{mintInvite.error.message}</AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
      <CardFooter className="justify-end">
        <Button onClick={() => mintInvite.mutate()} disabled={mintInvite.isPending}>
          {mintInvite.isPending ? (
            <Spinner data-icon="inline-start" />
          ) : (
            <TicketCheck data-icon="inline-start" />
          )}
          {invite ? "Create another invite" : "Create invite"}
        </Button>
      </CardFooter>
    </Card>
  );
}
