import { type FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { LifeBuoy } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";
import { AuthLayout } from "./AuthLayout";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const navigate = useNavigate();
  const forgot = useMutation({
    mutationFn: () => unwrap(api.POST("/api/auth/password/forgot", { body: { email } })),
    onSuccess: () => navigate(`/reset-password?email=${encodeURIComponent(email)}`, { replace: true }),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    forgot.mutate();
  };
  return (
    <AuthLayout title="Reset your password" description="Enter your email and we’ll send a single-use code." icon={<LifeBuoy aria-hidden="true" />} footer={<Link className="text-muted-foreground underline underline-offset-4" to="/login">Back to sign in</Link>}>
      <form onSubmit={submit}>
        <Field><FieldLabel htmlFor="forgot-email">Email</FieldLabel><Input id="forgot-email" type="email" autoComplete="email" value={email} disabled={forgot.isPending} onChange={(event) => setEmail(event.target.value)} required /></Field>
        {forgot.isError ? <p className="mt-3 text-sm text-destructive" role="alert">{forgot.error.message}</p> : null}
        <Button className="mt-6 w-full" type="submit" disabled={forgot.isPending}>{forgot.isPending ? <Spinner data-icon="inline-start" /> : null}{forgot.isPending ? "Sending…" : "Send reset code"}</Button>
      </form>
    </AuthLayout>
  );
}
