import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MailCheck } from "lucide-react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";
import { AuthLayout } from "./AuthLayout";
import { OtpInput } from "./OtpInput";
import { useCooldown } from "./useCooldown";

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const initialEmail = params.get("email") ?? "";
  const [email, setEmail] = useState(initialEmail);
  const [code, setCode] = useState("");
  const cooldown = useCooldown(60);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const verify = useMutation({
    mutationFn: () => unwrap(api.POST("/api/auth/verify-email", { body: { email, code } })),
    onSuccess: (me) => {
      queryClient.setQueryData(["auth", "me"], me);
      navigate("/", { replace: true });
    },
  });
  const resend = useMutation({
    mutationFn: () => unwrap(api.POST("/api/auth/resend-code", { body: { email } })),
    onSuccess: () => {
      setCode("");
      cooldown.start();
    },
  });
  if (!initialEmail) return <Navigate to="/register" replace />;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    verify.mutate();
  };
  return (
    <AuthLayout title="Check your email" description="Enter the six-digit code. It expires in 15 minutes." icon={<MailCheck aria-hidden="true" />}>
      <form onSubmit={submit}>
        <Field className="mb-5"><FieldLabel htmlFor="verify-email">Email</FieldLabel><Input id="verify-email" type="email" value={email} onChange={(event) => { setEmail(event.target.value); setCode(""); }} required /></Field>
        <OtpInput label="Verification code" value={code} onChange={setCode} disabled={verify.isPending} />
        {verify.isError ? <p className="mt-3 text-sm text-destructive" role="alert">{verify.error.message}</p> : null}
        {resend.isSuccess ? <p className="mt-3 text-sm text-muted-foreground" role="status">A new code is on its way.</p> : null}
        <Button className="mt-6 w-full" type="submit" disabled={code.length !== 6 || verify.isPending}>{verify.isPending ? <Spinner data-icon="inline-start" /> : null}{verify.isPending ? "Verifying…" : "Verify and continue"}</Button>
        <Button className="mt-2 w-full" type="button" variant="ghost" disabled={cooldown.seconds > 0 || resend.isPending} onClick={() => resend.mutate()}>
          {cooldown.seconds > 0 ? `Resend in ${cooldown.seconds}s` : "Resend code"}
        </Button>
      </form>
    </AuthLayout>
  );
}
