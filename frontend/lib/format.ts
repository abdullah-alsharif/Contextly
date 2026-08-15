export function formatBytes(bytes: number, decimals = 2): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(decimals)} MB`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** Today / Yesterday / MMM D / MMM D, YYYY (relative list timestamps). */
export function formatDateRelative(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const dayMs = 86_400_000;
  const dayDiff = Math.floor(
    (Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) -
      Date.UTC(date.getFullYear(), date.getMonth(), date.getDate())) /
      dayMs,
  );
  if (dayDiff <= 0) return "Today";
  if (dayDiff === 1) return "Yesterday";
  const sameYear = date.getFullYear() === now.getFullYear();
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

const FILE_ICONS: Record<string, string> = {
  pdf: "picture_as_pdf",
  txt: "description",
  md: "description",
  csv: "description",
  json: "description",
};

export function fileIcon(filename: string): string {
  return FILE_ICONS[filename.split(".").pop()?.toLowerCase() ?? ""] ?? "text_snippet";
}
