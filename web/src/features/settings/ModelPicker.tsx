import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { ProviderModelCatalog } from "./use-model-catalog";

const CUSTOM_VALUE = "__custom__";
const PROVIDER_DEFAULT = "__provider_default__";
const TUNING_LABEL_CLASS =
  "text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground";

type ModelEntry = ProviderModelCatalog["models"][number];

export function findCatalogModel(
  catalog: ProviderModelCatalog[] | undefined,
  modelId: string,
) {
  return (catalog ?? []).flatMap((provider) => provider.models)
    .find((model) => model.id === modelId);
}

function CapabilityBadges({ model }: { model: ModelEntry }) {
  if (!model.supportsReasoning && !model.supportsNativeSearch) return null;
  return (
    <span className="ml-auto flex gap-1">
      {model.supportsReasoning && (
        <Badge variant="outline" className="px-1.5 py-0 text-[10px] font-normal">Thinking</Badge>
      )}
      {model.supportsNativeSearch && (
        <Badge variant="outline" className="px-1.5 py-0 text-[10px] font-normal">Search</Badge>
      )}
    </span>
  );
}

export function ModelPicker({
  id, value, onChange, catalog,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  catalog: ProviderModelCatalog[] | undefined;
}) {
  const allModels = useMemo(() => (catalog ?? []).flatMap((p) => p.models), [catalog]);
  const knownIds = useMemo(() => new Set(allModels.map((m) => m.id)), [allModels]);
  // Base UI's <SelectValue> resolves labels through an internal items store
  // that items only populate while the popup is mounted, so on first paint
  // (nothing opened yet) it falls back to the raw value string. Resolve the
  // trigger label ourselves instead of relying on that store.
  const labelFor = (v: string | undefined) => {
    if (!v) return "Select a model";
    if (v === CUSTOM_VALUE) return "Custom model id…";
    return allModels.find((m) => m.id === v)?.label ?? v;
  };
  // Explicit escape hatch: once the user picks "Custom model id…", stay in
  // custom mode even while they clear/retype the field to something empty or
  // (transiently) matching a catalog id — only picking a real dropdown item
  // exits custom mode.
  const [customValue, setCustomValue] = useState<string | null>(null);
  const catalogReady = catalog !== undefined;
  const isCustom =
    customValue === value ||
    (catalogReady && value !== "" && !knownIds.has(value));
  const selectValue = isCustom ? CUSTOM_VALUE : value || undefined;

  return (
    <div className="flex flex-col gap-2">
      <Select
        value={selectValue}
        onValueChange={(v) => {
          if (!v) return;
          if (v === CUSTOM_VALUE) {
            setCustomValue(value);
            return;
          }
          setCustomValue(null);
          onChange(v);
        }}
      >
        <SelectTrigger id={id} className="w-full">
          <SelectValue>{(v) => labelFor(v as string | undefined)}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {(catalog ?? []).map((provider) => (
            <SelectGroup key={provider.provider}>
              <SelectLabel className="flex items-center gap-1.5">
                {provider.label}
                {!provider.hasKey && (
                  <Badge variant="outline" className="px-1.5 py-0 text-[10px] font-normal">No key</Badge>
                )}
              </SelectLabel>
              {provider.models.map((model) => (
                <SelectItem
                  key={model.id}
                  value={model.id}
                  disabled={!provider.hasKey}
                  title={!provider.hasKey ? `Add a ${provider.label} API key to use this model` : undefined}
                >
                  <span className="flex w-full items-center gap-1.5">
                    <span>{model.label}</span>
                    <CapabilityBadges model={model} />
                  </span>
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
          <SelectSeparator />
          <SelectItem value={CUSTOM_VALUE}>Custom model id…</SelectItem>
        </SelectContent>
      </Select>
      {isCustom && (
        <Input
          value={value}
          placeholder="provider:model-id (e.g. openai:gpt-5.5)"
          onChange={(e) => {
            setCustomValue(e.target.value);
            onChange(e.target.value);
          }}
        />
      )}
    </div>
  );
}

function TuningToggleGroup({
  label,
  value,
  levels,
  onChange,
}: {
  label: string;
  value: string | null;
  levels: string[];
  onChange: (value: string | null) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className={TUNING_LABEL_CLASS}>{label}</span>
      <ToggleGroup
        aria-label={label}
        value={[value ?? PROVIDER_DEFAULT]}
        onValueChange={(next) => {
          const picked = next.at(-1);
          if (!picked) return;
          onChange(picked === PROVIDER_DEFAULT ? null : picked);
        }}
      >
        <ToggleGroupItem value={PROVIDER_DEFAULT} className="h-7 rounded-full px-2.5 text-xs">
          Default
        </ToggleGroupItem>
        {levels.map((level) => (
          <ToggleGroupItem key={level} value={level} className="h-7 rounded-full px-2.5 text-xs">
            {level[0].toUpperCase() + level.slice(1)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  );
}

export function ModelTuningControls({
  modelId,
  reasoningEffort,
  catalog,
  onReasoningEffortChange,
}: {
  modelId: string;
  reasoningEffort: string | null;
  catalog: ProviderModelCatalog[] | undefined;
  onReasoningEffortChange: (value: string | null) => void;
}) {
  const model = findCatalogModel(catalog, modelId);
  if (!model || model.reasoningEfforts.length === 0) return null;

  return (
    <TuningToggleGroup
      label="Effort"
      value={reasoningEffort}
      levels={model.reasoningEfforts}
      onChange={onReasoningEffortChange}
    />
  );
}
