import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SuggestionPanel } from "./SuggestionPanel";

const envelope = {
  stale: false,
  suggestion: {
    kind: "skill" as const,
    key: "Kubernetes",
    repos: [
      {
        name: "foo/bar",
        url: "https://github.com/foo/bar",
        why: "Reference implementation",
        stars: 42,
        description: "Repository",
      },
    ],
    resources: [{ title: "Kubernetes docs", url: "https://k8s.io", kind: "doc" as const }],
    project: {
      title: "Mini scheduler",
      summary: "Build a scheduler",
      skillsDemonstrated: ["Go"],
    },
    bridge: "You know Docker, so Kubernetes is a short jump.",
    citations: ["https://k8s.io"],
    generatedAt: "2026-06-26T00:00:00Z",
  },
};

describe("SuggestionPanel", () => {
  it("renders repositories, resources, project, bridge, and sources", () => {
    render(
      <SuggestionPanel
        envelope={envelope}
        isLoading={false}
        onGenerate={() => {}}
        generating={false}
      />,
    );

    expect(screen.getByText("foo/bar")).toBeInTheDocument();
    expect(screen.getByText(/42/)).toBeInTheDocument();
    expect(screen.getByText("Kubernetes docs")).toBeInTheDocument();
    expect(screen.getByText("Mini scheduler")).toBeInTheDocument();
    expect(screen.getByText(/short jump/)).toBeInTheDocument();
    expect(screen.getByText("Sources")).toBeInTheDocument();
  });

  it("offers generation when no suggestion is cached", async () => {
    const onGenerate = vi.fn();
    render(
      <SuggestionPanel
        envelope={{ suggestion: null, stale: false }}
        isLoading={false}
        onGenerate={onGenerate}
        generating={false}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /how to close this gap/i }));

    expect(onGenerate).toHaveBeenCalledOnce();
  });

  it("marks stale advice and offers regeneration", () => {
    render(
      <SuggestionPanel
        envelope={{ ...envelope, stale: true }}
        isLoading={false}
        onGenerate={() => {}}
        generating={false}
      />,
    );

    expect(screen.getByText(/stale/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /regenerate/i })).toBeInTheDocument();
  });

  it("renders a retry action for query errors", async () => {
    const onRetry = vi.fn();
    render(
      <SuggestionPanel
        envelope={undefined}
        isLoading={false}
        isError
        onRetry={onRetry}
        onGenerate={() => {}}
        generating={false}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));

    expect(onRetry).toHaveBeenCalledOnce();
  });
});
