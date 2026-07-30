import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";
import { AuthLayout } from "./AuthLayout";
import { OtpInput } from "./OtpInput";
import { PasswordStrengthMeter } from "./PasswordStrengthMeter";

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const email = params.get("email") ?? "";
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const reset = useMutation({
    mutationFn: () => unwrap(api.POST("/api/auth/password/reset", { body: { email, code, newPassword } })),
    onSuccess: (me) => {
      queryClient.setQueryData(["auth", "me"], me);
      navigate("/", { replace: true });
    },
  });
  if (!email) return <Navigate to="/forgot-password" replace />;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    reset.mutate();
  };
  return (
    <AuthLayout title="Choose a new password" description={`Enter the code sent to ${email}. This signs out every other device.`} icon={<ShieldCheck aria-hidden="true" />}>
      <form onSubmit={submit}>
        <OtpInput label="Reset code" value={code} onChange={setCode} disabled={reset.isPending} />
        <Field className="mt-5"><FieldLabel htmlFor="reset-password">New password</FieldLabel><Input id="reset-password" type="password" autoComplete="new-password" value={newPassword} disabled={reset.isPending} onChange={(event) => setNewPassword(event.target.value)} required /><PasswordStrengthMeter password={newPassword} /></Field>
        {reset.isError ? <p className="mt-3 text-sm text-destructive" role="alert">{reset.error.message}</p> : null}
        <Button className="mt-6 w-full" type="submit" disabled={code.length !== 6 || !newPassword || reset.isPending}>{reset.isPending ? <Spinner data-icon="inline-start" /> : null}{reset.isPending ? "Resetting…" : "Reset password"}</Button>
      </form>
    </AuthLayout>
  );
}
