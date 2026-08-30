const RUN_LABELS: Record<string, string> = {
  addJobUrl: "Job import",
  coverLetter: "Cover-letter generation",
  coverLetterRevise: "Cover-letter revision",
  companyIntelligence: "Company research",
  discover: "Discovery",
  emailDraft: "Email-draft generation",
  gmailSync: "Gmail sync",
  "github-sync": "GitHub sync",
  h1bSponsorship: "H-1B sponsorship check",
  importUrls: "Job import",
  linkedinScrape: "LinkedIn import",
  maintainTaxonomy: "Taxonomy maintenance",
  "profile-build": "Profile build",
  pull: "Job pull",
  redo: "Pipeline redo",
  refreshClusters: "Skill regrouping",
  refresh: "Job refresh",
  reprocess: "Job reprocessing",
  revise: "Resume revision",
  tailor: "Tailoring",
  undoTaxonomyMaintenance: "Taxonomy maintenance undo",
};

const RUN_LABEL_KEYS = {
  addJobUrl: "runHistory.kinds.jobImport",
  coverLetter: "runHistory.kinds.coverLetterGeneration",
  coverLetterRevise: "runHistory.kinds.coverLetterRevision",
  companyIntelligence: "runHistory.kinds.companyResearch",
  discover: "runHistory.kinds.discovery",
  emailDraft: "runHistory.kinds.emailDraftGeneration",
  gmailSync: "runHistory.kinds.gmailSync",
  "github-sync": "runHistory.kinds.githubSync",
  h1bSponsorship: "runHistory.kinds.h1bSponsorshipCheck",
  importUrls: "runHistory.kinds.jobImport",
  linkedinScrape: "runHistory.kinds.linkedinImport",
  maintainTaxonomy: "runHistory.kinds.taxonomyMaintenance",
  "profile-build": "runHistory.kinds.profileBuild",
  pull: "runHistory.kinds.jobPull",
  redo: "runHistory.kinds.pipelineRedo",
  refreshClusters: "runHistory.kinds.skillRegrouping",
  refresh: "runHistory.kinds.jobRefresh",
  reprocess: "runHistory.kinds.jobReprocessing",
  revise: "runHistory.kinds.resumeRevision",
  tailor: "runHistory.kinds.tailoring",
  undoTaxonomyMaintenance: "runHistory.kinds.taxonomyMaintenanceUndo",
} as const;

export type RunLabelKey = (typeof RUN_LABEL_KEYS)[keyof typeof RUN_LABEL_KEYS];

export function runLabel(kind: string): string {
  return RUN_LABELS[kind] ?? kind;
}

export function runLabelKey(kind: string): RunLabelKey | null {
  return RUN_LABEL_KEYS[kind as keyof typeof RUN_LABEL_KEYS] ?? null;
}
