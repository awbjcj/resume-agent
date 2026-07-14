import { type FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { KeyRound, LockKeyhole } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";

export function PasswordCard() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const password = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/account/password", {
          body: { currentPassword, newPassword },
        }),
      ),
    onSuccess: () => {
      setCurrentPassword("");
      setNewPassword("");
      toast.success("Password updated");
    },
  });

  return (
    <form
      className="h-full"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        password.mutate();
      }}
    >
      <Card className="h-full">
        <CardHeader className="border-b">
          <div className="flex items-start gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
              <LockKeyhole aria-hidden="true" />
            </div>
            <div className="flex flex-col gap-1">
              <CardTitle>
                <h3>Change password</h3>
              </CardTitle>
              <CardDescription>
                Updating your password immediately signs out other sessions.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="current-password">Current password</FieldLabel>
              <Input
                id="current-password"
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                required
              />
            </Field>
            <Field data-invalid={password.isError || undefined}>
              <FieldLabel htmlFor="new-password">New password</FieldLabel>
              <Input
                id="new-password"
                type="password"
                autoComplete="new-password"
                minLength={12}
                value={newPassword}
                aria-invalid={password.isError || undefined}
                onChange={(event) => setNewPassword(event.target.value)}
                required
              />
              {password.isError ? <FieldError>{password.error.message}</FieldError> : null}
            </Field>
          </FieldGroup>
        </CardContent>
        <CardFooter className="justify-end">
          <Button type="submit" disabled={password.isPending}>
            {password.isPending ? (
              <Spinner data-icon="inline-start" />
            ) : (
              <KeyRound data-icon="inline-start" />
            )}
            Update password
          </Button>
        </CardFooter>
      </Card>
    </form>
  );
}
