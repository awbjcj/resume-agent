import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { api, unwrap } from "@/lib/api/client";

export function useMe() {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => unwrap(api.GET("/api/auth/me")),
    staleTime: 60_000,
  });
}

export function AuthGate({ children }: { children: ReactNode }) {
  const me = useMe();
  if (me.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6" aria-label="Checking session">
        <Skeleton className="h-40 w-full max-w-sm" />
      </div>
    );
  }
  if (me.isError) {
    return (
      <main className="flex min-h-screen items-center justify-center p-6">
        <Empty>
          <EmptyHeader>
            <EmptyTitle>Could not verify your session</EmptyTitle>
            <EmptyDescription>{me.error.message}</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button variant="outline" onClick={() => void me.refetch()}>Retry</Button>
          </EmptyContent>
        </Empty>
      </main>
    );
  }
  if (me.data.authRequired && !me.data.username) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}
