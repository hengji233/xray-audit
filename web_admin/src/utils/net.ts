export function parseSourceIp(src: string | undefined): string {
  const value = (src || "").trim();
  if (!value) {
    return "";
  }

  if (value.startsWith("[") && value.includes("]")) {
    return value.slice(1, value.indexOf("]"));
  }

  if (value.includes(":")) {
    const parts = value.split(":");
    if (parts.length === 2 && /^\d+$/.test(parts[1])) {
      return parts[0];
    }
  }

  return value;
}
