import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ProviderModelCatalog = components["schemas"]["ProviderModelCatalog"];

export function useModelCatalog() {
  return useQuery({
    queryKey: ["model-catalog"],
    queryFn: (): Promise<ProviderModelCatalog[]> =>
      unwrap(api.GET("/api/config/models/catalog", {})) as Promise<ProviderModelCatalog[]>,
  });
}
