import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { useSaveSecrets } from "./use-secrets";

describe("useSaveSecrets", () => {
  it("invalidates the model catalog after an API key changes", async () => {
    server.use(
      http.put("/api/secrets", () =>
        HttpResponse.json([{ key: "openaiApiKey", isSet: true, hint: "1234" }]),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    queryClient.setQueryData(["model-catalog"], [{ provider: "openai", hasKey: false }]);
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useSaveSecrets(), { wrapper });

    await act(() => result.current.mutateAsync({ openaiApiKey: "sk-openai-1234" }));

    await waitFor(() =>
      expect(queryClient.getQueryState(["model-catalog"])?.isInvalidated).toBe(true),
    );
  });
});
