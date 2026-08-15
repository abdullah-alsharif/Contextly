export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
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
