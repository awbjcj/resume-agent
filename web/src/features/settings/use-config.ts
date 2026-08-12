import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { paths } from "@/lib/api/schema";

export type ConfigPath =
  | "/api/config/search"
  | "/api/config/review"
  | "/api/config/review-deep"
  | "/api/config/prune"
  | "/api/config/render"
  | "/api/config/style-guide"
  | "/api/config/profile"
  | "/api/config/models";

type GetBody<P extends ConfigPath> =
  paths[P]["get"]["responses"][200]["content"]["application/json"];

export function useConfig<P extends ConfigPath>(path: P) {
  return useQuery({
    queryKey: ["config", path],
    queryFn: () => unwrap(api.GET(path, {} as never)) as Promise<GetBody<P>>,
  });
}

export function useSaveConfig<P extends ConfigPath>(path: P) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: GetBody<P>) =>
      unwrap(api.PUT(path, { body } as never)) as Promise<GetBody<P>>,
    onSuccess: (saved) => {
      qc.setQueryData(["config", path], saved);
      toast.success("Saved");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}
