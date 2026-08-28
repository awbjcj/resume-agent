import { type FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";
import { AuthLayout } from "./AuthLayout";
import { AuthNotice, callbackErrorMessage } from "./AuthNotice";
import { GoogleButton } from "./GoogleButton";
import { PasswordStrengthMeter } from "./PasswordStrengthMeter";

export function RegisterPage() {
  const [params] = useSearchParams();
  // In invite-only deployments, a first Google sign-in with no matching account
  // lands here so the user can supply the invite and restart the passwordless
  // Google flow. The query string is display-only; the callback verifies the
  // Google identity again before creating the account.
  const fromGoogle = params.get("from") === "google";
  const [email, setEmail] = useState(() => params.get("email") ?? "");
  const [displayName, setDisplayName] = useState(() => params.get("name") ?? "");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const calloutError = callbackErrorMessage(params.get("error"));
  const navigate = useNavigate();
  const register = useMutation({
    mutationFn: () => unwrap(api.POST("/api/auth/register", { body: { email, password, inviteCode, displayName: displayName || null } })),
    onSuccess: () => navigate(`/verify-email?email=${encodeURIComponent(email)}`, { replace: true }),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    register.mutate();
  };
  return (
    <AuthLayout
      title="Create your workspace"
      description="Use the private invite code from your administrator."
      icon={<UserPlus aria-hidden="true" />}
      footer={<p className="text-center text-muted-foreground">Already have an account? <Link className="font-medium text-foreground underline underline-offset-4" to="/login">Sign in</Link></p>}
    >
      {calloutError ? <AuthNotice tone="error">{calloutError}</AuthNotice> : null}
      {!calloutError && fromGoogle ? (
        <AuthNotice tone="info">
          No account matches{" "}
          <span className="font-medium text-foreground">{email || "that Google address"}</span>{" "}
          yet. Enter your invite code if required, then continue with Google. You won’t
          need a password or an emailed verification code.
        </AuthNotice>
      ) : null}
      <form onSubmit={submit}>
        <Field data-invalid={register.isError || undefined}>
          <FieldLabel htmlFor="register-invite">Invite code <span className="font-normal text-muted-foreground">(if required)</span></FieldLabel>
          <Input id="register-invite" autoComplete="off" value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} aria-invalid={register.isError || undefined} />
          {register.isError ? <FieldError>{register.error.message}</FieldError> : null}
        </Field>
        <div className="mt-4">
          <GoogleButton mode="register" invite={inviteCode} />
        </div>
        <p className="mt-2 text-center text-xs text-muted-foreground">
          Google verifies your email and creates a passwordless account.
        </p>
        <div className="my-5 flex items-center gap-3 text-xs text-muted-foreground"><span className="h-px flex-1 bg-border" />or register with email<span className="h-px flex-1 bg-border" /></div>
        <FieldGroup>
          <Field><FieldLabel htmlFor="register-email">Email</FieldLabel><Input id="register-email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></Field>
          <Field><FieldLabel htmlFor="register-name">Display name <span className="font-normal text-muted-foreground">(optional)</span></FieldLabel><Input id="register-name" autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></Field>
          <Field><FieldLabel htmlFor="register-password">Password</FieldLabel><Input id="register-password" type="password" autoComplete="new-password" minLength={12} value={password} onChange={(event) => setPassword(event.target.value)} required /><PasswordStrengthMeter password={password} /></Field>
        </FieldGroup>
        <Button className="mt-6 w-full" type="submit" disabled={register.isPending}>{register.isPending ? <Spinner data-icon="inline-start" /> : null}{register.isPending ? "Sending code…" : "Create account"}</Button>
      </form>
    </AuthLayout>
  );
}
