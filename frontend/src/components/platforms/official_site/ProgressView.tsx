"use client";

import { ProductRecord } from "@/types";
import type { StreamStatus } from "@/hooks/useScrapeStream";
import SnapshotTable from "@/components/SnapshotTable";
import { officialSiteColumns } from "./columns";

interface Props {
  brand: string;
  section: string;
  categories: string[];
  products: ProductRecord[];
  isStreaming: boolean;
  isDone: boolean;
  status: StreamStatus;
}

export default function ProgressView({
  brand,
  section,
  categories,
  products,
  isStreaming,
  isDone,
  status,
}: Props) {
  // Scraper walks `categories` in selection order. Each streamed product
  // carries its `category`. Latest product's category = currently scraping;
  // earlier in the selection list = done; later = pending. On `isDone`, any
  // category that produced ≥1 product is done; nothing is "active".
  const lastCategory = products.at(-1)?.category ?? null;
  const activeIdx = isDone
    ? -1
    : lastCategory !== null
    ? categories.indexOf(lastCategory)
    : isStreaming
    ? 0
    : -1;
  const produced = new Set(
    products.map((p) => p.category).filter((c): c is string => !!c),
  );
  const doneCount = isDone ? produced.size : Math.max(0, activeIdx);

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
              {products.length} products · {doneCount} of {categories.length} categories complete
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
            const isCatDone = isDone
              ? produced.has(cat)
              : activeIdx !== -1 && i < activeIdx;
            const isActive = activeIdx !== -1 && i === activeIdx;
            let classes =
              "rounded-full px-3 py-1 text-xs font-medium transition-colors ";
            if (isCatDone) {
              classes += "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300/50";
            } else if (isActive) {
              classes += "bg-accent-soft text-accent ring-1 ring-accent/30 pulse-soft";
            } else {
              classes += "bg-muted text-muted-fg";
            }
            return (
              <span key={cat} className={classes}>
                {isCatDone && "✓ "}
                {cat}
              </span>
            );
          })}
        </div>
      </div>

      <SnapshotTable
        products={products}
        columns={officialSiteColumns}
        emptyMessage="Waiting for products…"
      />
    </div>
  );
}
