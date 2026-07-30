import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LogOut, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { useMe } from "@/features/auth/AuthGate";
import { GoogleButton } from "@/features/auth/GoogleButton";
import { api, unwrap } from "@/lib/api/client";

export function SecurityCard() {
  const me = useMe();
  const queryClient = useQueryClient();
  const [unlinkOpen, setUnlinkOpen] = useState(false);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const unlink = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/account/google")),
    onSuccess: (next) => {
      queryClient.setQueryData(["auth", "me"], next);
      setUnlinkOpen(false);
      toast.success("Google sign-in removed");
    },
  });
  const revoke = useMutation({
    mutationFn: () => unwrap(api.POST("/api/account/sessions/revoke-all")),
    onSuccess: () => {
      setRevokeOpen(false);
      toast.success("Other sessions signed out");
    },
  });
  if (!me.data) return null;
  return (
    <Card>
      <CardHeader className="border-b">
        <div className="flex items-start gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-muted"><ShieldCheck aria-hidden="true" /></div>
          <div><CardTitle><h3>Sign-in security</h3></CardTitle><CardDescription>Manage linked identity and active sessions.</CardDescription></div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div><p className="font-medium">Google</p><p className="text-sm text-muted-foreground">{me.data.googleLinked ? "Google is linked to this account." : "Google is not linked."}</p></div>
          {me.data.googleLinked ? (
            <AlertDialog open={unlinkOpen} onOpenChange={setUnlinkOpen}>
              <AlertDialogTrigger render={<Button variant="outline" />}>Unlink Google</AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader><AlertDialogTitle>Unlink Google?</AlertDialogTitle><AlertDialogDescription>You will need your password for future sign-ins.</AlertDialogDescription></AlertDialogHeader>
                <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction variant="destructive" disabled={unlink.isPending} onClick={() => unlink.mutate()}>{unlink.isPending ? <Spinner data-icon="inline-start" /> : null}Unlink</AlertDialogAction></AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          ) : <div className="w-full sm:w-56"><GoogleButton mode="login" /></div>}
        </div>
        <div className="flex flex-col gap-3 border-t pt-6 sm:flex-row sm:items-center sm:justify-between">
          <div><p className="font-medium">Active sessions</p><p className="text-sm text-muted-foreground">Keep this device signed in and revoke every other session.</p></div>
          <AlertDialog open={revokeOpen} onOpenChange={setRevokeOpen}>
            <AlertDialogTrigger render={<Button variant="outline" />}><LogOut aria-hidden="true" />Sign out everywhere</AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader><AlertDialogTitle>Sign out other devices?</AlertDialogTitle><AlertDialogDescription>Every existing session except this one will stop working immediately.</AlertDialogDescription></AlertDialogHeader>
              <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction disabled={revoke.isPending} onClick={() => revoke.mutate()}>{revoke.isPending ? <Spinner data-icon="inline-start" /> : null}Continue</AlertDialogAction></AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </CardContent>
    </Card>
  );
}
