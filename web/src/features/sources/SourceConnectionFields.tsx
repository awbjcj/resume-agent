import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SOURCE_PROVIDERS, type SourceDraft, type SourceProvider } from "./source-connection";

type Props = {
  draft: SourceDraft;
  onChange: (patch: Partial<SourceDraft>) => void;
};

const TOKEN_COPY: Partial<Record<SourceProvider, { label: string; placeholder: string; help: string }>> = {
  greenhouse: { label: "Board token", placeholder: "acme", help: "The final segment in a Greenhouse board URL." },
  lever: { label: "Company token", placeholder: "acme", help: "The company segment after jobs.lever.co/." },
  ashby: { label: "Organization slug", placeholder: "acme", help: "The organization segment after jobs.ashbyhq.com/." },
  smartrecruiters: { label: "Company identifier", placeholder: "Acme", help: "The company identifier used by SmartRecruiters." },
  workable: { label: "Account token", placeholder: "acme", help: "The account segment used on apply.workable.com." },
  recruitee: { label: "Company subdomain", placeholder: "acme", help: "The subdomain before .recruitee.com." },
  personio: { label: "Company subdomain", placeholder: "acme", help: "The subdomain before .jobs.personio." },
  breezy: { label: "Company subdomain", placeholder: "acme", help: "The subdomain before .breezy.hr." },
  jazzhr: { label: "Company subdomain", placeholder: "acme", help: "The subdomain before .applytojob.com." },
  bamboohr: { label: "Company subdomain", placeholder: "acme", help: "The subdomain before .bamboohr.com." },
};

export function SourceConnectionFields({ draft, onChange }: Props) {
  const tokenCopy = TOKEN_COPY[draft.provider];
  return (
    <FieldGroup>
      <Field>
        <FieldLabel htmlFor="source-provider">Connection type</FieldLabel>
        <Select
          value={draft.provider}
          onValueChange={(value) => onChange({ provider: value as SourceProvider })}
        >
          <SelectTrigger id="source-provider" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectLabel>Provider</SelectLabel>
              {SOURCE_PROVIDERS.map((provider) => (
                <SelectItem key={provider.value} value={provider.value}>
                  <span className="flex flex-col items-start">
                    <span>{provider.label}</span>
                    <span className="text-xs text-muted-foreground">{provider.description}</span>
                  </span>
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <FieldDescription>Use a native connection when you know the hiring platform.</FieldDescription>
      </Field>

      {draft.provider === "auto" ? (
        <Field>
          <FieldLabel htmlFor="source-url">Careers or board URL</FieldLabel>
          <Input id="source-url" type="url" value={draft.url} placeholder="https://careers.example.com" onChange={(event) => onChange({ url: event.target.value })} />
          <FieldDescription>We will detect the provider and make a live request before saving.</FieldDescription>
        </Field>
      ) : null}

      {tokenCopy ? (
        <Field>
          <FieldLabel htmlFor="source-token">{tokenCopy.label}</FieldLabel>
          <Input id="source-token" value={draft.token} placeholder={tokenCopy.placeholder} autoCapitalize="none" autoCorrect="off" onChange={(event) => onChange({ token: event.target.value })} />
          <FieldDescription>{tokenCopy.help}</FieldDescription>
        </Field>
      ) : null}

      {draft.provider === "workday" ? (
        <div className="grid gap-4 sm:grid-cols-3">
          <Field><FieldLabel htmlFor="workday-tenant">Tenant</FieldLabel><Input id="workday-tenant" value={draft.tenant} placeholder="acme" onChange={(event) => onChange({ tenant: event.target.value })} /></Field>
          <Field><FieldLabel htmlFor="workday-dc">Data center</FieldLabel><Input id="workday-dc" value={draft.datacenter} placeholder="wd5" onChange={(event) => onChange({ datacenter: event.target.value })} /></Field>
          <Field><FieldLabel htmlFor="workday-site">Career site</FieldLabel><Input id="workday-site" value={draft.site} placeholder="Careers" onChange={(event) => onChange({ site: event.target.value })} /></Field>
        </div>
      ) : null}

      {draft.provider === "personio" ? (
        <Field>
          <FieldLabel htmlFor="personio-country">Region</FieldLabel>
          <Select value={draft.country} onValueChange={(value) => onChange({ country: value as "com" | "de" })}>
            <SelectTrigger id="personio-country" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent><SelectGroup><SelectItem value="com">Global (.com)</SelectItem><SelectItem value="de">Germany (.de)</SelectItem></SelectGroup></SelectContent>
          </Select>
        </Field>
      ) : null}
    </FieldGroup>
  );
}
