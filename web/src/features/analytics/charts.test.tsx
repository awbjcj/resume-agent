import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { changeLanguage } from "@/i18n";
import { CycleTimeChart, toCycleRows } from "./CycleTimeChart";
import { OfferComparisonChart, toOfferRows } from "./OfferComparisonChart";
import { PipelineTimelineChart, toLanes } from "./PipelineTimelineChart";
import { StageFlowChart, toSankeyData } from "./StageFlowChart";

describe("analytics chart transforms", () => {
  it("builds named Sankey nodes with indexed links and source denominators", () => {
    const data = toSankeyData([
      { source: "application_submitted", target: "recruiter_screen", count: 5 },
      { source: "application_submitted", target: "no_response", count: 2 },
    ]);
    expect(data.nodes[0].name).toBe("Application submitted");
    expect(data.links[0]).toMatchObject({ source: 0, target: 1, value: 5, total: 7 });
    expect(data.links[1].color).toBe("var(--chart-5)");
  });

  it("drops self-links and backward links before Recharts sees the Sankey graph", () => {
    const data = toSankeyData([
      { source: "technical_round", target: "technical_round", count: 3 },
      { source: "technical_round", target: "recruiter_screen", count: 2 },
      { source: "technical_round", target: "offer_received", count: 1 },
    ]);
    expect(data.links).toHaveLength(1);
    expect(data.links[0]).toMatchObject({ sourceKind: "technical_round", targetKind: "offer_received" });
  });

  it("marks cycle rows by sample confidence", () => {
    const rows = toCycleRows([
      { fromKind: "recruiter_screen", toKind: "technical_round", medianDays: 6, sampleSize: 12 },
      { fromKind: "application_submitted", toKind: "recruiter_screen", medianDays: 1.5, sampleSize: 1 },
    ]);
    expect(rows[0]).toMatchObject({
      label: "Application submitted → Recruiter screen",
      lowConfidence: true,
    });
    expect(rows[1].lowConfidence).toBe(false);
  });

  it("sorts lanes against an injected clock and centers a zero-span layout", () => {
    const now = new Date("2026-03-10T12:00:00Z");
    const lanes = toLanes(
      [
        { jobId: 1, company: "Later", title: "SWE", status: "interview", events: [{ kind: "technical_round", sequence: 1, occurredAt: "2026-03-20T12:00:00Z", allDay: false, result: "pending" }] },
        { jobId: 2, company: "Sooner", title: "SWE", status: "interview", events: [{ kind: "technical_round", sequence: 1, occurredAt: "2026-03-10T12:00:00Z", allDay: false, result: "pending" }] },
      ],
      now,
    );
    expect(lanes.map((lane) => lane.company)).toEqual(["Sooner", "Later"]);
    const sameDay = toLanes([
      { jobId: 2, company: "Sooner", title: "SWE", status: "interview", events: [{ kind: "technical_round", sequence: 1, occurredAt: "2026-03-10T12:00:00Z", allDay: false, result: "pending" }] },
    ], now);
    expect(sameDay[0].events[0].position).toBe(50);
  });

  it("preserves currency identity in offer rows", () => {
    const rows = toOfferRows([
      { eventId: 11, jobId: 1, company: "Acme", sequence: 1, occurredAt: "2026-03-20T12:00:00Z", compBase: 180000, compBonus: null, compEquityAnnual: null, compSigning: null, compCurrency: "USD", totalComp: 180000 },
    ]);
    expect(rows[0]).toMatchObject({ company: "Acme", base: 180000, bonus: 0, currency: "USD" });
  });

  it("localizes stage names and generated offer fallbacks in Chinese", async () => {
    await changeLanguage("zh-CN");

    const flow = toSankeyData([
      { source: "application_submitted", target: "recruiter_screen", count: 5 },
    ]);
    const cycles = toCycleRows([
      { fromKind: "recruiter_screen", toKind: "technical_round", medianDays: 6, sampleSize: 12 },
    ]);
    const offers = toOfferRows([
      { eventId: 12, jobId: 1, company: null, sequence: 1, occurredAt: "2026-03-20T12:00:00Z", compBase: null, compBonus: null, compEquityAnnual: null, compSigning: null, compCurrency: null, totalComp: null },
    ]);

    expect(flow.nodes.map((node) => node.name)).toEqual(["已投递", "招聘方初筛"]);
    expect(cycles[0].label).toBe("招聘方初筛 → 技术面");
    expect(offers[0]).toMatchObject({ company: "录用通知", label: "录用通知 · #1", currency: "未注明币种" });
  });
});

describe("analytics chart empty states", () => {
  it("explains missing history and omits an empty offer chart", () => {
    render(
      <>
        <StageFlowChart flows={[]} />
        <CycleTimeChart cycleTimes={[]} />
        <PipelineTimelineChart pipeline={[]} />
      </>,
    );
    expect(screen.getAllByText(/not enough history/i)).toHaveLength(2);
    expect(screen.getByText(/no active applications/i)).toBeInTheDocument();
    const { container } = render(<OfferComparisonChart offers={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
