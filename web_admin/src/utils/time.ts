export function parseApiDateTime(raw: string): Date {
  if (!raw) {
    return new Date(0);
  }
  const hasTz = /[zZ]|[+-]\d{2}:\d{2}$/.test(raw);
  return new Date(hasTz ? raw : `${raw}Z`);
}

export function formatDateTime(raw: string, useUtc: boolean): string {
  const date = parseApiDateTime(raw);
  if (Number.isNaN(date.getTime())) {
    return raw;
  }
  const formatter = new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: useUtc ? "UTC" : undefined,
  });
  return formatter.format(date);
}

export function formatUnixSeconds(unixSeconds: number, useUtc: boolean): string {
  return formatDateTime(new Date(unixSeconds * 1000).toISOString(), useUtc);
}

export function getRangeIso(hours: number): [string, string] {
  const to = new Date();
  const from = new Date(Date.now() - hours * 60 * 60 * 1000);
  return [from.toISOString(), to.toISOString()];
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

export function toPickerDateTime(raw: Date): string {
  return `${raw.getFullYear()}-${pad2(raw.getMonth() + 1)}-${pad2(raw.getDate())}T${pad2(raw.getHours())}:${pad2(raw.getMinutes())}:${pad2(raw.getSeconds())}`;
}

export function parsePickerDateTime(raw: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})$/.exec(raw.trim());
  if (!m) {
    return null;
  }
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const hour = Number(m[4]);
  const minute = Number(m[5]);
  const second = Number(m[6]);
  const date = new Date(year, month - 1, day, hour, minute, second, 0);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date;
}

export function getPickerRange(hours: number): [string, string] {
  const now = new Date();
  const from = new Date(now.getTime() - hours * 60 * 60 * 1000);
  return [toPickerDateTime(from), toPickerDateTime(now)];
}

export function pickerRangeToUtcIso(range: [string, string]): [string, string] {
  const from = parsePickerDateTime(range[0]);
  const to = parsePickerDateTime(range[1]);
  if (!from || !to) {
    throw new Error("invalid time range");
  }
  return [from.toISOString(), to.toISOString()];
}

export function pickerRangeDurationSeconds(range: [string, string], fallbackSeconds: number): number {
  const from = parsePickerDateTime(range[0]);
  const to = parsePickerDateTime(range[1]);
  if (!from || !to) {
    return fallbackSeconds;
  }
  const deltaMs = to.getTime() - from.getTime();
  if (deltaMs <= 0) {
    return fallbackSeconds;
  }
  return Math.max(1, Math.floor(deltaMs / 1000));
}

export function shiftPickerRangeToNow(
  range: [string, string] | undefined,
  defaultWindowSeconds: number
): [string, string] {
  const durationSeconds = range
    ? pickerRangeDurationSeconds(range, defaultWindowSeconds)
    : defaultWindowSeconds;
  const now = new Date();
  const from = new Date(now.getTime() - durationSeconds * 1000);
  return [toPickerDateTime(from), toPickerDateTime(now)];
}
