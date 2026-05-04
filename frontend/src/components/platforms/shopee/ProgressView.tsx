"use client";

import { DoneInfo, LogEntry, ProductRecord } from "@/types";
import type { StreamStatus } from "@/hooks/useScrapeStream";
import SnapshotTable, { productRecordColumns } from "@/components/SnapshotTable";

const SHOPEE_COLUMNS = productRecordColumns("shopee");

interface ProgressViewProps {
  products: ProductRecord[];
  logs: LogEntry[];
  doneInfo: DoneInfo | null;
  isStreaming: boolean;
  status: StreamStatus;
}

export default function ProgressView({
  products,
  doneInfo,
  isStreaming,
  status,
}: ProgressViewProps) {
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
            <h2 className="text-lg font-semibold">Shopee products</h2>
            <p className="text-sm text-muted-fg mt-1">
              {products.length}
              {doneInfo ? ` of ${doneInfo.count}` : ""} products scraped
            </p>
          </div>
          <span
            className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${
              isStreaming
                ? "bg-accent-soft text-accent ring-1 ring-accent/30"
                : status === "done"
                  ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300/50"
                  : "bg-pink-100 text-pink-600 ring-1 ring-pink-300/50"
            }`}
          >
            {statusLabel}
          </span>
        </div>
      </div>

      <SnapshotTable
        rows={products as unknown as Record<string, unknown>[]}
        columns={SHOPEE_COLUMNS}
      />
    </div>
  );
}
