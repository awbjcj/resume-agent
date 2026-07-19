import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { GmailCard } from "./GmailCard";

describe("GmailCard", () => {
  it("offers connect when disconnected", async () => {
    server.use(
      http.get("*/api/gmail/status", () =>
        HttpResponse.json({
          connected: false,
          scopes: [],
          draftCapable: false,
          clientSource: "platform",
        }),
      ),
    );
    render(<GmailCard />, { wrapper: withQueryClient });
    expect(
      await screen.findByRole("button", { name: /connect gmail/i }),
    ).toBeInTheDocument();
  });

  it("offers reconnect when compose scope is missing", async () => {
    server.use(
      http.get("*/api/gmail/status", () =>
        HttpResponse.json({
          connected: true,
          scopes: ["readonly"],
          draftCapable: false,
          clientSource: "own",
        }),
      ),
    );
    render(<GmailCard />, { wrapper: withQueryClient });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /reconnect/i }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: /disconnect/i }),
    ).toBeInTheDocument();
  });
});
