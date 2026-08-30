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

const PIPELINE_STAGE_LABEL_KEYS = {
  raw: "job.stages.raw",
  shortlisted: "job.stages.shortlisted",
  approved: "job.stages.approved",
  tailored: "job.stages.tailored",
  rendered: "job.stages.rendered",
  rejected: "job.stages.rejected",
} as const;

type PipelineStageLabelKey =
  (typeof PIPELINE_STAGE_LABEL_KEYS)[keyof typeof PIPELINE_STAGE_LABEL_KEYS];

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

export function normalizePipelineStage(stage: string) {
  return stage.trim().toLowerCase();
}

export function pipelineStageLabel(
  stage: string,
  translate?: (key: PipelineStageLabelKey) => string,
) {
  const normalizedStage = normalizePipelineStage(stage);
  const labelKey =
    PIPELINE_STAGE_LABEL_KEYS[normalizedStage as keyof typeof PIPELINE_STAGE_LABEL_KEYS];
  if (labelKey && translate) return translate(labelKey);

  return normalizedStage.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function openStagesFromParam(stage: string | null): Set<string> {
  return stage && (PIPELINE_STAGE_ORDER as readonly string[]).includes(stage)
    ? new Set([stage])
    : initialOpenPipelineStages();
}
