import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LogOutIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { api, unwrap } from "@/lib/api/client";
import { useMe } from "./AuthGate";

export function LogoutButton() {
  const { t } = useTranslation();
  const me = useMe();
  const queryClient = useQueryClient();
  const logout = useMutation({
    mutationFn: () => unwrap(api.POST("/api/auth/logout")),
    onSuccess: () => {
      queryClient.setQueryData(["auth", "me"], {
        username: null,
        authRequired: true,
      });
    },
  });
  if (!me.data?.authRequired) return null;
  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={logout.isPending}
      onClick={() => logout.mutate()}
    >
      {logout.isPending ? (
        <Spinner data-icon="inline-start" />
      ) : (
        <LogOutIcon data-icon="inline-start" />
      )}
      {logout.isPending ? t("shell.signingOut") : t("shell.signOut")}
    </Button>
  );
}
