import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { changeLanguage } from "@/i18n";
import { ApplicationsTable } from "./ApplicationsTable";

const cell = (over: Record<string, unknown> = {}) => ({
  occurredAt: "2026-03-09T12:00:00Z",
  allDay: true,
  result: "advanced",
  modality: "virtual",
  platform: "zoom",
  platformOther: null,
  interviewers: "A. Interviewer",
  notes: null,
  ...over,
});

const table = {
  technicalRoundColumns: 2,
  rows: [
    {
      jobId: 42,
      company: "Acme",
      title: "Senior SWE",
      status: "interview",
      source: "greenhouse",
      fitScore: 82,
      overflowRounds: 3,
      customCount: 1,
      totalComp: null,
      compCurrency: null,
      offerDeadline: null,
      cells: {
        application_submitted: cell({ occurredAt: "2026-03-03T12:00:00Z" }),
        technical_round_1: cell(),
      },
    },
  ],
};

describe("ApplicationsTable", () => {
  it("links each application, grows rounds, and owns horizontal overflow", () => {
    const { container } = render(
      <MemoryRouter>
        <ApplicationsTable table={table as never} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /Acme/ })).toHaveAttribute(
      "href",
      "/pipeline?job=42",
    );
    expect(screen.getByRole("columnheader", { name: "Tech 2" })).toBeInTheDocument();
    expect(screen.getByText("+3")).toBeInTheDocument();
    expect(container.querySelector(".min-w-0.overflow-x-auto")).not.toBeNull();
  });

  it("makes compact cell metadata available without relying on title", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ApplicationsTable table={table as never} />
      </MemoryRouter>,
    );
    const detail = screen.getByRole("button", { name: /technical round 1 details/i });
    await user.click(detail);
    expect(screen.getByText(/Advanced · Virtual · Zoom · A. Interviewer/i)).toBeVisible();
  });

  it("localizes timeline stages, status, and event metadata in Chinese", async () => {
    await changeLanguage("zh-CN");
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ApplicationsTable table={table as never} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("columnheader", { name: "技术面 2" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "职位" })).toBeInTheDocument();
    expect(screen.getByText("面试中")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "技术面 1详情" }));
    expect(screen.getByText(/进入下一轮 · 线上 · Zoom · A. Interviewer/)).toBeVisible();
  });

  it("shows an empty state", () => {
    render(<ApplicationsTable table={{ rows: [], technicalRoundColumns: 0 } as never} />);
    expect(screen.getByText(/no applications tracked yet/i)).toBeInTheDocument();
  });
});
