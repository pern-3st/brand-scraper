"use client";

import { CategoryResult, LogEntry } from "@/types";
import type { StreamStatus } from "@/hooks/useScrapeStream";

interface ProgressViewProps {
  brand: string;
  section: string;
  categories: string[];
  categoryResults: CategoryResult[];
  logs: LogEntry[];
  isStreaming: boolean;
  isDone: boolean;
  status: StreamStatus;
}

export default function ProgressView({
  brand,
  section,
  categories,
  categoryResults,
  isStreaming,
  isDone,
  status,
}: ProgressViewProps) {
  const completedNames = new Set(categoryResults.map((r) => r.category));
  const doneCount = categoryResults.length;
  const inProgressIdx = categories.findIndex((c) => !completedNames.has(c));

  const statusLabel = (() => {
    if (status === "connecting") return "Connecting…";
    if (status === "streaming") return "Scraping…";
    if (status === "done") return "Complete";
    if (status === "cancelled") return "Cancelled";
    if (status === "error") return "Error";
    return status;
  })();

  return (
    <div className="space-y-4">
      <div className="rounded-2xl bg-card p-6 shadow-md shadow-accent/5 ring-1 ring-border">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">
              Scraping {brand || "brand"}{" "}
              <span className="text-foreground/40 font-normal">
                — {section.charAt(0).toUpperCase() + section.slice(1)}
              </span>
            </h2>
            <p className="text-sm text-muted-fg mt-1">
              {doneCount} of {categories.length} categories complete
            </p>
          </div>
          <span
            className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${
              isDone
                ? status === "done"
                  ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300/50"
                  : "bg-pink-100 text-pink-600 ring-1 ring-pink-300/50"
                : "bg-accent-soft text-accent ring-1 ring-accent/30"
            }`}
          >
            {statusLabel}
          </span>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {categories.map((cat, i) => {
            const result = categoryResults.find((r) => r.category === cat);
            const isActive = isStreaming && i === inProgressIdx;

            let classes =
              "rounded-full px-3 py-1 text-xs font-medium transition-colors ";
            if (result) {
              classes +=
                result.status === "found"
                  ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300/50"
                  : "bg-pink-100 text-pink-600 ring-1 ring-pink-300/50";
            } else if (isActive) {
              classes +=
                "bg-accent-soft text-accent ring-1 ring-accent/30 pulse-soft";
            } else {
              classes += "bg-muted text-muted-fg";
            }

            return (
              <span key={cat} className={classes}>
                {result?.status === "found" && "✓ "}
                {result?.status === "not_found" && "✗ "}
                {cat}
              </span>
            );
          })}
        </div>
      </div>

      {categoryResults.length > 0 && (
        <div className="rounded-2xl bg-card ring-1 ring-border overflow-hidden">
          <div className="px-6 py-3 border-b border-border text-sm font-semibold text-foreground/60 uppercase tracking-wider">
            Live results
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-muted/50 text-left text-foreground/60">
                  <th className="py-2 px-6 font-medium">Category</th>
                  <th className="py-2 px-4 font-medium">Status</th>
                  <th className="py-2 px-4 font-medium">Lowest</th>
                  <th className="py-2 px-4 font-medium">Highest</th>
                  <th className="py-2 px-4 font-medium">Scanned</th>
                </tr>
              </thead>
              <tbody>
                {categoryResults.map((r) => (
                  <tr
                    key={r.category}
                    className="border-t border-border hover:bg-muted/30 transition-colors"
                  >
                    <td className="py-2 px-6 font-medium">{r.category}</td>
                    <td className="py-2 px-4">
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                          r.status === "found"
                            ? "bg-emerald-100 text-emerald-700"
                            : "bg-pink-100 text-pink-600"
                        }`}
                      >
                        {r.status === "found" ? "Found" : "Not found"}
                      </span>
                    </td>
                    <td className="py-2 px-4">
                      {r.lowest_price !== null
                        ? r.lowest_price.toFixed(2)
                        : "—"}
                    </td>
                    <td className="py-2 px-4">
                      {r.highest_price !== null
                        ? r.highest_price.toFixed(2)
                        : "—"}
                    </td>
                    <td className="py-2 px-4">{r.products_scanned}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
