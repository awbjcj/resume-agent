import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ProfileMatrix = components["schemas"]["MatrixOut"];

export function useMatrix() {
  return useQuery({
    queryKey: ["profile-matrix"],
    queryFn: () =>
      unwrap(api.GET("/api/profile/matrix", {} as never)) as Promise<ProfileMatrix>,
  });
}
