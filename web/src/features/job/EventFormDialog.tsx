import { useState, type ReactElement } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { dateInputParts, zonedDateTimeToIso } from "@/lib/calendar-date";
import {
  KIND_LABELS,
  MODALITY_LABELS,
  PLATFORM_LABELS,
  RESULT_LABELS,
  REPEATABLE_KINDS,
} from "./event-labels";
import type {
  ApplicationEvent,
  ApplicationEventCreate,
} from "./use-application-events";

export { KIND_LABELS, MODALITY_LABELS, PLATFORM_LABELS, RESULT_LABELS };

type FormState = {
  kind: string;
  sequence: string;
  customLabel: string;
  date: string;
  time: string;
  allDay: boolean;
  timezone: string;
  durationMinutes: string;
  modality: string;
  platform: string;
  platformOther: string;
  locationOrLink: string;
  interviewers: string;
  result: string;
  notes: string;
  reflection: string;
  compBase: string;
  compBonus: string;
  compEquityAnnual: string;
  compSigning: string;
  compCurrency: string;
};

function initialState(event?: ApplicationEvent): FormState {
  const parts = dateInputParts(event?.occurredAt, event?.allDay ?? true, event?.timezone);
  return {
    kind: event?.kind ?? "application_submitted",
    sequence: event?.sequenceOverride?.toString() ?? "",
    customLabel: event?.customLabel ?? "",
    date: parts.date,
    time: parts.time || "09:00",
    allDay: event?.allDay ?? true,
    timezone:
      event?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC",
    durationMinutes: event?.durationMinutes?.toString() ?? "",
    modality: event?.modality ?? "",
    platform: event?.platform ?? "",
    platformOther: event?.platformOther ?? "",
    locationOrLink: event?.locationOrLink ?? "",
    interviewers: event?.interviewers ?? "",
    result: event?.result ?? "pending",
    notes: event?.notes ?? "",
    reflection: event?.reflection ?? "",
    compBase: event?.compBase?.toString() ?? "",
    compBonus: event?.compBonus?.toString() ?? "",
    compEquityAnnual: event?.compEquityAnnual?.toString() ?? "",
    compSigning: event?.compSigning?.toString() ?? "",
    compCurrency: event?.compCurrency ?? "USD",
  };
}

const nullable = (value: string) => value.trim() || null;
const numberOrNull = (value: string) => (value === "" ? null : Number(value));

function NativeSelect({
  id,
  label,
  value,
  values,
  allowBlank = true,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  values: Record<string, string>;
  allowBlank?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm focus-visible:border-ring focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {allowBlank && <option value="">Not specified</option>}
        {Object.entries(values).map(([option, optionLabel]) => (
          <option key={option} value={option}>
            {optionLabel}
          </option>
        ))}
      </select>
    </div>
  );
}

export function EventFormDialog({
  trigger,
  event,
  onSubmit,
}: {
  trigger: ReactElement;
  event?: ApplicationEvent;
  onSubmit: (body: ApplicationEventCreate) => void | Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(() => initialState(event));
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const set = <K extends keyof FormState>(field: K, value: FormState[K]) =>
    setForm((current) => ({ ...current, [field]: value }));

  const setDialogOpen = (nextOpen: boolean) => {
    if (nextOpen) {
      setForm(initialState(event));
      setError(null);
    }
    setOpen(nextOpen);
  };

  const submit = async () => {
    if (form.kind === "custom" && !form.customLabel.trim()) {
      setError("Label is required for an Other event.");
      return;
    }
    if (form.kind !== "custom" && !form.date) {
      setError("Date is required for this stage.");
      return;
    }
    let occurredAt: string | null = null;
    let effectiveTimezone: string | null = null;
    if (form.date) {
      if (form.allDay) {
        occurredAt = `${form.date}T00:00:00.000Z`;
      } else {
        try {
          effectiveTimezone =
            form.timezone.trim() ||
            Intl.DateTimeFormat().resolvedOptions().timeZone ||
            "UTC";
          occurredAt = zonedDateTimeToIso(
            form.date,
            form.time || "09:00",
            effectiveTimezone,
          );
        } catch (cause) {
          setError(
            cause instanceof RangeError && cause.message.includes("does not exist")
              ? cause.message
              : "Enter a valid IANA timezone, such as America/New_York.",
          );
          return;
        }
      }
    }
    const body: ApplicationEventCreate = {
      kind: form.kind,
      sequence: numberOrNull(form.sequence),
      customLabel: nullable(form.customLabel),
      occurredAt,
      allDay: form.allDay,
      timezone: form.allDay ? null : effectiveTimezone,
      durationMinutes: numberOrNull(form.durationMinutes),
      modality: nullable(form.modality),
      platform: nullable(form.platform),
      platformOther: nullable(form.platformOther),
      locationOrLink: nullable(form.locationOrLink),
      interviewers: nullable(form.interviewers),
      result: form.result,
      notes: nullable(form.notes),
      reflection: nullable(form.reflection),
      compBase: numberOrNull(form.compBase),
      compBonus: numberOrNull(form.compBonus),
      compEquityAnnual: numberOrNull(form.compEquityAnnual),
      compSigning: numberOrNull(form.compSigning),
      compCurrency: form.kind === "offer_received" ? nullable(form.compCurrency) : null,
    };
    setError(null);
    setIsSubmitting(true);
    try {
      await onSubmit(body);
      setOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to save this event.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setDialogOpen}>
      <DialogTrigger render={trigger} />
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{event ? "Edit event" : "Add timeline event"}</DialogTitle>
          <DialogDescription>
            Record what happened, when it happened, and what you want to remember.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 sm:grid-cols-2">
          <NativeSelect
            id="event-kind"
            label="Stage"
            value={form.kind}
            values={KIND_LABELS}
            allowBlank={false}
            onChange={(value) => set("kind", value)}
          />
          {form.kind === "custom" && (
            <div className="space-y-1.5">
              <Label htmlFor="event-custom-label">Label</Label>
              <Input
                id="event-custom-label"
                value={form.customLabel}
                onChange={(e) => set("customLabel", e.target.value)}
              />
            </div>
          )}
          {REPEATABLE_KINDS.has(form.kind) && (
            <div className="space-y-1.5">
              <Label htmlFor="event-sequence">Round number</Label>
              <Input
                id="event-sequence"
                type="number"
                min="1"
                value={form.sequence}
                onChange={(e) => set("sequence", e.target.value)}
                placeholder="Auto"
              />
              <p className="text-xs text-muted-foreground">Leave blank to order this round by date.</p>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="event-date">Date</Label>
            <Input
              id="event-date"
              type="date"
              value={form.date}
              onChange={(e) => set("date", e.target.value)}
            />
          </div>
          {!form.allDay && (
            <div className="space-y-1.5">
              <Label htmlFor="event-timezone">Timezone</Label>
              <Input
                id="event-timezone"
                value={form.timezone}
                onChange={(e) => set("timezone", e.target.value)}
                placeholder="America/New_York"
              />
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="event-time">Time</Label>
            <div className="flex items-center gap-3">
              <Input
                id="event-time"
                type="time"
                value={form.time}
                disabled={form.allDay}
                onChange={(e) => set("time", e.target.value)}
              />
              <label className="flex shrink-0 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.allDay}
                  onChange={(e) => set("allDay", e.target.checked)}
                />
                All day
              </label>
            </div>
          </div>
          <NativeSelect
            id="event-modality"
            label="Modality"
            value={form.modality}
            values={MODALITY_LABELS}
            onChange={(value) => set("modality", value)}
          />
          <NativeSelect
            id="event-platform"
            label="Platform"
            value={form.platform}
            values={PLATFORM_LABELS}
            onChange={(value) => set("platform", value)}
          />
          {form.platform === "other" && (
            <div className="space-y-1.5">
              <Label htmlFor="event-platform-other">Platform name</Label>
              <Input
                id="event-platform-other"
                value={form.platformOther}
                onChange={(e) => set("platformOther", e.target.value)}
              />
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="event-duration">Duration (minutes)</Label>
            <Input
              id="event-duration"
              type="number"
              min="1"
              value={form.durationMinutes}
              onChange={(e) => set("durationMinutes", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="event-location">Location or link</Label>
            <Input
              id="event-location"
              value={form.locationOrLink}
              onChange={(e) => set("locationOrLink", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="event-interviewers">Interviewers</Label>
            <Input
              id="event-interviewers"
              value={form.interviewers}
              onChange={(e) => set("interviewers", e.target.value)}
            />
          </div>
          <NativeSelect
            id="event-result"
            label="Result"
            value={form.result}
            values={RESULT_LABELS}
            allowBlank={false}
            onChange={(value) => set("result", value)}
          />
        </div>

        {form.kind === "offer_received" && (
          <fieldset className="grid gap-3 rounded-xl border bg-muted/20 p-4 sm:grid-cols-2">
            <legend className="px-1 text-sm font-semibold">Compensation</legend>
            {[
              ["compBase", "Base salary"],
              ["compBonus", "Annual bonus"],
              ["compEquityAnnual", "Equity per year"],
              ["compSigning", "Signing bonus"],
            ].map(([field, label]) => (
              <div className="space-y-1.5" key={field}>
                <Label htmlFor={`event-${field}`}>{label}</Label>
                <Input
                  id={`event-${field}`}
                  type="number"
                  min="0"
                  value={form[field as keyof FormState] as string}
                  onChange={(e) => set(field as keyof FormState, e.target.value)}
                />
              </div>
            ))}
            <div className="space-y-1.5">
              <Label htmlFor="event-currency">Currency</Label>
              <Input
                id="event-currency"
                maxLength={3}
                value={form.compCurrency}
                onChange={(e) => set("compCurrency", e.target.value.toUpperCase())}
              />
            </div>
          </fieldset>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="event-notes">Notes</Label>
            <Textarea
              id="event-notes"
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
              placeholder="Questions, logistics, or what was discussed"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="event-reflection">Reflection</Label>
            <Textarea
              id="event-reflection"
              value={form.reflection}
              onChange={(e) => set("reflection", e.target.value)}
              placeholder="What worked and what to change next time"
            />
          </div>
        </div>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
            Cancel
          </Button>
          <Button type="button" disabled={isSubmitting} onClick={() => void submit()}>
            {isSubmitting ? "Saving…" : "Save event"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
