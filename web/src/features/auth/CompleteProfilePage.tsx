import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AtSign } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";
import { AuthLayout } from "./AuthLayout";
import { OtpInput } from "./OtpInput";
import { useCooldown } from "./useCooldown";

export function CompleteProfilePage() {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const cooldown = useCooldown();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const requestCode = useMutation({
    mutationFn: () => unwrap(api.POST("/api/account/email", { body: { email } })),
    onSuccess: () => { setSent(true); cooldown.start(); },
  });
  const confirm = useMutation({
    mutationFn: () => unwrap(api.POST("/api/account/email/verify", { body: { email, code } })),
    onSuccess: (me) => {
      queryClient.setQueryData(["auth", "me"], me);
      navigate("/", { replace: true });
    },
  });
  const active = sent ? confirm : requestCode;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (sent) confirm.mutate(); else requestCode.mutate();
  };
  return (
    <AuthLayout title="Add your email" description="Add a verified address so you can recover your password." icon={<AtSign aria-hidden="true" />}>
      <form onSubmit={submit}>
        <Field><FieldLabel htmlFor="complete-email">Email</FieldLabel><Input id="complete-email" type="email" autoComplete="email" value={email} disabled={active.isPending} onChange={(event) => { setEmail(event.target.value); setSent(false); setCode(""); }} required /></Field>
        {sent ? <div className="mt-5"><OtpInput label="Verification code" value={code} onChange={setCode} disabled={confirm.isPending} /></div> : null}
        {active.isError ? <p className="mt-3 text-sm text-destructive" role="alert">{active.error.message}</p> : null}
        <Button className="mt-6 w-full" type="submit" disabled={active.isPending || (sent && code.length !== 6)}>{active.isPending ? <Spinner data-icon="inline-start" /> : null}{sent ? "Verify and continue" : "Send verification code"}</Button>
        {sent ? <Button className="mt-2 w-full" type="button" variant="ghost" disabled={cooldown.seconds > 0 || requestCode.isPending} onClick={() => requestCode.mutate()}>{cooldown.seconds > 0 ? `Resend in ${cooldown.seconds}s` : "Resend code"}</Button> : null}
      </form>
    </AuthLayout>
  );
}
