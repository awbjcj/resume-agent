import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";

export function RegisterPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const register = useMutation({
    mutationFn: async () => {
      await unwrap(api.POST("/api/auth/register", {
        body: { username, password, inviteCode },
      }));
      return unwrap(api.POST("/api/auth/login", { body: { username, password } }));
    },
    onSuccess: (me) => {
      queryClient.setQueryData(["auth", "me"], me);
      navigate("/", { replace: true });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    register.mutate();
  };

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-muted/30 p-6">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,var(--primary),transparent_42%)] opacity-10" />
      <Card className="relative w-full max-w-md">
        <form onSubmit={submit}>
          <CardHeader>
            <div className="mb-2 flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <UserPlus aria-hidden="true" />
            </div>
            <CardTitle>Create your workspace</CardTitle>
            <CardDescription>Use the private invite code from your administrator.</CardDescription>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              <Field><FieldLabel htmlFor="register-username">Username</FieldLabel><Input id="register-username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></Field>
              <Field><FieldLabel htmlFor="register-password">Password</FieldLabel><Input id="register-password" type="password" autoComplete="new-password" minLength={12} value={password} onChange={(event) => setPassword(event.target.value)} required /></Field>
              <Field data-invalid={register.isError || undefined}>
                <FieldLabel htmlFor="register-invite">Invite code</FieldLabel>
                <Input id="register-invite" autoComplete="off" value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} required aria-invalid={register.isError || undefined} />
                {register.isError && <FieldError>{register.error.message}</FieldError>}
              </Field>
            </FieldGroup>
          </CardContent>
          <CardFooter className="flex-col gap-3">
            <Button className="w-full" type="submit" disabled={register.isPending}>
              {register.isPending && <Spinner data-icon="inline-start" />}
              {register.isPending ? "Creating workspace…" : "Create account"}
            </Button>
            <Button variant="link" render={<Link to="/login">Already have an account? Sign in</Link>} />
          </CardFooter>
        </form>
      </Card>
    </main>
  );
}
