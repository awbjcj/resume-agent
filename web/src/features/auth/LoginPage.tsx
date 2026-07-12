import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRoundIcon } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

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

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const login = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/auth/login", { body: { username, password } })),
    onSuccess: (me) => {
      queryClient.setQueryData(["auth", "me"], me);
      navigate("/", { replace: true });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate();
  };

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-muted/30 p-6">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,var(--border)_1px,transparent_1px),linear-gradient(to_bottom,var(--border)_1px,transparent_1px)] bg-[size:3rem_3rem] opacity-30" />
      <Card className="relative w-full max-w-sm">
        <form onSubmit={submit}>
          <CardHeader>
            <div className="mb-2 flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <KeyRoundIcon aria-hidden="true" />
            </div>
            <CardTitle>Resume Agent</CardTitle>
            <CardDescription>Sign in to your private command center.</CardDescription>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              <Field data-invalid={login.isError || undefined}>
                <FieldLabel htmlFor="login-username">Username</FieldLabel>
                <Input
                  id="login-username"
                  autoComplete="username"
                  value={username}
                  disabled={login.isPending}
                  aria-invalid={login.isError || undefined}
                  onChange={(event) => setUsername(event.target.value)}
                  required
                />
              </Field>
              <Field data-invalid={login.isError || undefined}>
                <FieldLabel htmlFor="login-password">Password</FieldLabel>
                <Input
                  id="login-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  disabled={login.isPending}
                  aria-invalid={login.isError || undefined}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
                {login.isError && <FieldError>{login.error.message}</FieldError>}
              </Field>
            </FieldGroup>
          </CardContent>
          <CardFooter className="flex-col gap-3">
            <Button className="w-full" type="submit" disabled={login.isPending}>
              {login.isPending && <Spinner data-icon="inline-start" />}
              {login.isPending ? "Signing in…" : "Sign in"}
            </Button>
            <Button variant="link" render={<Link to="/register">Create an account with an invite</Link>} />
          </CardFooter>
        </form>
      </Card>
    </main>
  );
}
