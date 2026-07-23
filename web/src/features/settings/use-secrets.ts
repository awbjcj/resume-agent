import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";

export type SecretStatus = { key: string; isSet: boolean; hint: string | null };
export type SecretsPatch = Record<string, string | null>;

export function useSecrets() {
  return useQuery({
    queryKey: ["secrets"],
    queryFn: () => unwrap(api.GET("/api/secrets", {} as never)) as Promise<SecretStatus[]>,
  });
}

export function useSaveSecrets() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: SecretsPatch) =>
      unwrap(api.PUT("/api/secrets", { body: patch } as never)) as Promise<SecretStatus[]>,
    onSuccess: (statuses) => {
      qc.setQueryData(["secrets"], statuses);
      qc.invalidateQueries({ queryKey: ["setup-status"] });
      qc.invalidateQueries({ queryKey: ["model-catalog"] });
      toast.success("Keys updated");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}
