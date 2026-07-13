export type SourceProvider =
  | "auto"
  | "greenhouse"
  | "lever"
  | "ashby"
  | "workday"
  | "smartrecruiters"
  | "workable"
  | "recruitee"
  | "personio"
  | "breezy"
  | "jazzhr"
  | "bamboohr";

export type SourceConnection = {
  provider: SourceProvider;
  url?: string;
  token?: string;
  tenant?: string;
  datacenter?: string;
  site?: string;
  country: "com" | "de";
  label?: string | null;
};

export type SourceDraft = {
  provider: SourceProvider;
  url: string;
  token: string;
  tenant: string;
  datacenter: string;
  site: string;
  country: "com" | "de";
};

export const EMPTY_SOURCE_DRAFT: SourceDraft = {
  provider: "auto",
  url: "",
  token: "",
  tenant: "",
  datacenter: "",
  site: "",
  country: "com",
};

export const SOURCE_PROVIDERS: Array<{
  value: SourceProvider;
  label: string;
  description: string;
}> = [
  { value: "auto", label: "Auto-detect", description: "Paste any supported career page" },
  { value: "greenhouse", label: "Greenhouse", description: "Board token" },
  { value: "lever", label: "Lever", description: "Company token" },
  { value: "ashby", label: "Ashby", description: "Organization slug" },
  { value: "workday", label: "Workday", description: "Tenant, data center, and site" },
  { value: "smartrecruiters", label: "SmartRecruiters", description: "Company identifier" },
  { value: "workable", label: "Workable", description: "Account token" },
  { value: "recruitee", label: "Recruitee", description: "Company subdomain" },
  { value: "personio", label: "Personio", description: "Company subdomain and region" },
  { value: "breezy", label: "Breezy HR", description: "Company subdomain" },
  { value: "jazzhr", label: "JazzHR", description: "Company subdomain" },
  { value: "bamboohr", label: "BambooHR", description: "Company subdomain" },
];

export function connectionBody(draft: SourceDraft, label: string): SourceConnection {
  const displayLabel = label.trim() || null;
  if (draft.provider === "auto") {
    return {
      provider: "auto",
      url: draft.url.trim(),
      country: draft.country,
      label: displayLabel,
    };
  }
  if (draft.provider === "workday") {
    return {
      provider: "workday",
      tenant: draft.tenant.trim(),
      datacenter: draft.datacenter.trim(),
      site: draft.site.trim(),
      country: draft.country,
      label: displayLabel,
    };
  }
  return {
    provider: draft.provider,
    token: draft.token.trim(),
    country: draft.country,
    label: displayLabel,
  };
}

export function isConnectionComplete(draft: SourceDraft): boolean {
  if (draft.provider === "auto") return Boolean(draft.url.trim());
  if (draft.provider === "workday") {
    return Boolean(draft.tenant.trim() && draft.datacenter.trim() && draft.site.trim());
  }
  return Boolean(draft.token.trim());
}
