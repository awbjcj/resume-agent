import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";
import { AuthLayout } from "./AuthLayout";
import { AuthNotice, callbackErrorMessage } from "./AuthNotice";
import { GoogleButton } from "./GoogleButton";

export function LoginPage() {
  const [params] = useSearchParams();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  // The Google callback can only report a refusal by redirecting here with
  // ?error=<code>; without this the page rendered as an empty form.
  const calloutError = callbackErrorMessage(params.get("error"));
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const login = useMutation({
    mutationFn: () => unwrap(api.POST("/api/auth/login", { body: { identifier, password } })),
    onSuccess: (me) => {
      queryClient.setQueryData(["auth", "me"], me);
      navigate(me.needsEmail ? "/complete-profile" : "/", { replace: true });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate();
  };
  return (
    <AuthLayout
      title="Welcome back"
      description="Sign in to continue to your private workspace."
      icon={<KeyRound aria-hidden="true" />}
      footer={<p className="text-center text-muted-foreground">New here? <Link className="font-medium text-foreground underline underline-offset-4" to="/register">Create an account</Link></p>}
    >
      {calloutError ? <AuthNotice tone="error">{calloutError}</AuthNotice> : null}
      <form onSubmit={submit}>
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="login-email">Email</FieldLabel>
            <Input id="login-email" type="text" autoComplete="username" value={identifier} disabled={login.isPending} onChange={(event) => setIdentifier(event.target.value)} required />
          </Field>
          <Field data-invalid={login.isError || undefined}>
            <div className="flex items-center justify-between">
              <FieldLabel htmlFor="login-password">Password</FieldLabel>
              <Link className="text-xs text-muted-foreground underline underline-offset-4" to="/forgot-password">Forgot password?</Link>
            </div>
            <Input id="login-password" type="password" autoComplete="current-password" value={password} disabled={login.isPending} aria-invalid={login.isError || undefined} onChange={(event) => setPassword(event.target.value)} required />
            {login.isError ? <FieldError>{login.error.message}</FieldError> : null}
          </Field>
        </FieldGroup>
        <Button className="mt-6 w-full" type="submit" disabled={login.isPending}>
          {login.isPending ? <Spinner data-icon="inline-start" /> : null}
          {login.isPending ? "Signing in…" : "Sign in"}
        </Button>
        <div className="my-5 flex items-center gap-3 text-xs text-muted-foreground"><span className="h-px flex-1 bg-border" />or<span className="h-px flex-1 bg-border" /></div>
        <GoogleButton mode="login" />
      </form>
    </AuthLayout>
  );
}
