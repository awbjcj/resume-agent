import { describe, expect, it } from "vitest";

import {
  initialOpenPipelineStages,
  normalizePipelineStage,
  openStagesFromParam,
} from "./pipeline-stages";

describe("openStagesFromParam", () => {
  it("opens exactly the requested stage", () => {
    expect(openStagesFromParam("approved")).toEqual(new Set(["approved"]));
  });

  it("falls back to the defaults without a param", () => {
    expect(openStagesFromParam(null)).toEqual(initialOpenPipelineStages());
  });

  it("ignores unknown stage names", () => {
    expect(openStagesFromParam("bogus")).toEqual(initialOpenPipelineStages());
  });
});

describe("normalizePipelineStage", () => {
  it("canonicalizes legacy casing and surrounding whitespace", () => {
    expect(normalizePipelineStage("  Shortlisted ")).toBe("shortlisted");
  });
});
