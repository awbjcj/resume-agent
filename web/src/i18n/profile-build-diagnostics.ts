import type { TFunction } from "i18next";

type ReportLineKind = "warning" | "conflict" | "anchor" | "verificationDrop";

function verifierReasonLabel(t: TFunction, reason: string): string {
  if (reason === "no supporting excerpt") return t("profileBuild.verification.noSupportingExcerpt");
  if (reason === "not confirmed by verifier") return t("profileBuild.verification.notConfirmed");

  const excerpt = /^excerpt not found in source: (.+)$/.exec(reason);
  if (excerpt) return t("profileBuild.verification.excerptNotFound", { excerpt: excerpt[1] });

  const number = /^number (.+) not in source$/.exec(reason);
  if (number) return t("profileBuild.verification.numberNotFound", { token: number[1] });

  const name = /^name (.+) not in source$/.exec(reason);
  if (name) return t("profileBuild.verification.nameNotFound", { token: name[1] });

  const tech = /^tech (.+) not in source$/.exec(reason);
  if (tech) return t("profileBuild.verification.techNotFound", { token: tech[1] });

  return reason;
}

export function profileBuildStatusLabel(t: TFunction, status: string): string {
  if (status === "cached") return t("profileBuild.status.cached");
  if (status === "extracted") return t("profileBuild.status.extracted");
  if (status === "source-changed") return t("profileBuild.status.sourceChanged");
  if (status === "missing") return t("profileBuild.status.missing");
  if (status === "stale") return t("profileBuild.status.stale");

  const failed = /^failed: (.+)$/.exec(status);
  if (failed) return t("profileBuild.status.failed", { reason: failed[1] });

  const stale = /^stale: (.+)$/.exec(status);
  if (stale) return t("profileBuild.status.staleWithReason", { reason: stale[1] });

  return status;
}

function profileBuildWarningLabel(t: TFunction, warning: string): string {
  if (warning === "GitHub rate limit hit; cached docs were preserved. Set GITHUB_TOKEN to raise the limit.") {
    return t("profileBuild.warning.githubRateLimit");
  }

  const harvestFailure = /^GitHub harvest failed for (.+?): (.+)$/.exec(warning);
  if (harvestFailure) {
    return t("profileBuild.warning.githubHarvestFailed", {
      repository: harvestFailure[1],
      reason: harvestFailure[2],
    });
  }

  const projectSkipped = /^project extraction skipped for (\d+) document\(s\): no project agent configured$/.exec(warning);
  if (projectSkipped) {
    return t("profileBuild.warning.projectExtractionSkipped", { count: Number(projectSkipped[1]) });
  }

  const synthesisSkipped = /^synthesis skipped for (\d+) document\(s\): no synthesis\/entailment agent configured$/.exec(warning);
  if (synthesisSkipped) {
    return t("profileBuild.warning.synthesisSkipped", { count: Number(synthesisSkipped[1]) });
  }

  const githubMetadataSkipped = /^GitHub metadata merge skipped: (.+)$/.exec(warning);
  if (githubMetadataSkipped) return t("profileBuild.warning.githubMetadataSkipped", { reason: githubMetadataSkipped[1] });

  const skillInference = /^skill inference failed: (.+)$/.exec(warning);
  if (skillInference) return t("profileBuild.warning.skillInferenceFailed", { reason: skillInference[1] });

  const aspectClassification = /^bullet aspect classification failed: (.+)$/.exec(warning);
  if (aspectClassification) return t("profileBuild.warning.aspectClassificationFailed", { reason: aspectClassification[1] });

  const githubListing = /^GitHub repository listing failed: (.+)$/.exec(warning);
  if (githubListing) return t("profileBuild.warning.githubListingFailed", { reason: githubListing[1] });

  const dossierSkipped = /^(.+?): dossier (.+) skipped \(max (\d+) per repo\)$/.exec(warning);
  if (dossierSkipped) {
    return t("profileBuild.warning.dossierSkipped", {
      repository: dossierSkipped[1],
      dossier: dossierSkipped[2],
      limit: dossierSkipped[3],
    });
  }

  const dossierWrongRepo = /^(.+?): dossier (.+) targets a different repository; skipped$/.exec(warning);
  if (dossierWrongRepo) {
    return t("profileBuild.warning.dossierWrongRepository", {
      repository: dossierWrongRepo[1],
      dossier: dossierWrongRepo[2],
    });
  }

  const manualAlias = /^Manual alias '(.+)' could not be reattached -- its target skill '(.+)' was not found\.$/.exec(warning);
  if (manualAlias) {
    return t("profileBuild.warning.manualAliasNotFound", {
      alias: manualAlias[1],
      target: manualAlias[2],
    });
  }

  return warning;
}

function profileBuildConflictLabel(t: TFunction, conflict: string): string {
  const match = /^(.+): ([^ ]+) (.+) kept over (.+) from (.+)$/.exec(conflict);
  if (match) {
    return t("profileBuild.conflict", {
      label: match[1],
      field: match[2],
      kept: match[3],
      discarded: match[4],
      source: match[5],
    });
  }

  const summary = /^(.+): (.+) kept over (.+) from (.+)$/.exec(conflict);
  if (summary) {
    return t("profileBuild.summaryConflict", {
      label: summary[1],
      kept: summary[2],
      discarded: summary[3],
      source: summary[4],
    });
  }

  return conflict;
}

function profileBuildAnchorLabel(t: TFunction, decision: string): string {
  const missing = /^(.+): anchor (.+) not found — kept as a project$/.exec(decision);
  if (missing) return t("profileBuild.anchor.missing", { source: missing[1], anchor: missing[2] });

  const added = /^(.+): \+(\d+) bullets on (.+)$/.exec(decision);
  if (added) return t("profileBuild.anchor.added", {
    source: added[1],
    count: Number(added[2]),
    target: added[3],
  });

  return decision;
}

function profileBuildVerificationDropLabel(t: TFunction, drop: string): string {
  const match = /^(.+): (.+) — (.+)$/.exec(drop);
  if (!match) return drop;

  return t("profileBuild.verification.drop", {
    source: match[1],
    claim: match[2],
    reason: verifierReasonLabel(t, match[3]),
  });
}

export function profileBuildReportLineLabel(
  t: TFunction,
  kind: ReportLineKind,
  line: string,
): string {
  switch (kind) {
    case "warning":
      return profileBuildWarningLabel(t, line);
    case "conflict":
      return profileBuildConflictLabel(t, line);
    case "anchor":
      return profileBuildAnchorLabel(t, line);
    case "verificationDrop":
      return profileBuildVerificationDropLabel(t, line);
  }
}

export function evidencePortfolioWarningLabel(t: TFunction, warning: string): string {
  const fallback = /^Evidence planner unavailable \((.+)\); deterministic fallback used\.$/.exec(warning);
  if (fallback) {
    const reason = fallback[1] === "planner unavailable"
      ? t("profileBuild.evidencePlanner.plannerUnavailable")
      : fallback[1];
    return t("profileBuild.evidencePlanner.fallback", { reason });
  }
  if (warning === "Planner unavailable; deterministic evidence selection was used.") {
    return t("profileBuild.evidencePlanner.legacyFallback");
  }
  return warning;
}
