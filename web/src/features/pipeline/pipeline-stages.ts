export const PIPELINE_STAGE_ORDER = [
  "tailored",
  "rendered",
  "approved",
  "shortlisted",
  "raw",
  "rejected",
] as const;

const stageRank = new Map<string, number>(
  PIPELINE_STAGE_ORDER.map((stage, index) => [stage, index]),
);

export function orderPipelineStages(stages: Iterable<string>) {
  return [...stages].sort((left, right) => {
    const leftRank = stageRank.get(left) ?? Number.MAX_SAFE_INTEGER;
    const rightRank = stageRank.get(right) ?? Number.MAX_SAFE_INTEGER;
    return leftRank - rightRank || left.localeCompare(right);
  });
}

export function initialOpenPipelineStages() {
  return new Set<string>(["tailored", "rendered"]);
}

export function pipelineStageLabel(stage: string) {
  return stage.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function openStagesFromParam(stage: string | null): Set<string> {
  return stage && (PIPELINE_STAGE_ORDER as readonly string[]).includes(stage)
    ? new Set([stage])
    : initialOpenPipelineStages();
}
