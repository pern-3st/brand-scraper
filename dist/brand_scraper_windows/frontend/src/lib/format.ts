export function formatPlatform(platform: string | null | undefined): string {
  if (!platform) return "";
  return platform
    .split("_")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}
