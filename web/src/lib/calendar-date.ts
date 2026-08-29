const pad = (part: number) => String(part).padStart(2, "0");

function zonedParts(value: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(value);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((item) => item.type === type)?.value ?? 0);
  return {
    year: part("year"),
    month: part("month"),
    day: part("day"),
    hour: part("hour"),
    minute: part("minute"),
    second: part("second"),
  };
}

export function dateInputParts(
  value: string | null | undefined,
  allDay: boolean,
  timeZone?: string | null,
) {
  if (!value) return { date: "", time: "" };
  if (allDay) return { date: value.slice(0, 10), time: "" };
  const moment = new Date(value);
  if (timeZone) {
    const parts = zonedParts(moment, timeZone);
    return {
      date: `${parts.year}-${pad(parts.month)}-${pad(parts.day)}`,
      time: `${pad(parts.hour)}:${pad(parts.minute)}`,
    };
  }
  return {
    date: `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())}`,
    time: `${pad(moment.getHours())}:${pad(moment.getMinutes())}`,
  };
}

export function zonedDateTimeToIso(date: string, time: string, timeZone: string): string {
  const [year, month, day] = date.split("-").map(Number);
  const [hour, minute] = time.split(":").map(Number);
  const desired = Date.UTC(year, month - 1, day, hour, minute, 0);
  const offsets = new Set<number>();
  for (let hours = -36; hours <= 36; hours += 6) {
    const sample = desired + hours * 3_600_000;
    const rendered = zonedParts(new Date(sample), timeZone);
    const renderedAsUtc = Date.UTC(
      rendered.year,
      rendered.month - 1,
      rendered.day,
      rendered.hour,
      rendered.minute,
      rendered.second,
    );
    offsets.add(renderedAsUtc - sample);
  }
  const candidates = [...offsets]
    .map((offset) => desired - offset)
    .filter((candidate) => {
      const rendered = zonedParts(new Date(candidate), timeZone);
      return (
        rendered.year === year &&
        rendered.month === month &&
        rendered.day === day &&
        rendered.hour === hour &&
        rendered.minute === minute &&
        rendered.second === 0
      );
    });
  if (candidates.length === 0) {
    throw new RangeError(`Local time ${date} ${time} does not exist in ${timeZone}`);
  }
  // A fall-back overlap has two valid instants. Choose the earlier occurrence
  // consistently; existing events can still round-trip through their UTC value.
  return new Date(Math.min(...candidates)).toISOString();
}

export function formatCalendarDate(
  value: string,
  allDay: boolean,
  options: Intl.DateTimeFormatOptions,
  locale?: string,
): string {
  return new Date(value).toLocaleString(locale, {
    ...options,
    ...(allDay ? { timeZone: "UTC" } : {}),
  });
}
