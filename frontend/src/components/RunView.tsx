"use client";

import { useEffect, useState } from "react";
import { getRun, getBrand } from "@/lib/api";
import type { ProductRecord, Source } from "@/types";
import SnapshotTable from "./SnapshotTable";
import { shopeeColumns } from "./platforms/shopee/columns";
import { officialSiteColumns } from "./platforms/official_site/columns";

interface RunPayload {
  _status: string;
  _meta: Record<string, unknown>;
  records: unknown[];
}

export default function RunView({
  brandId,
  sourceId,
  runId,
}: {
  brandId: string;
  sourceId: string;
  runId: string;
}) {
  const [payload, setPayload] = useState<RunPayload | null>(null);
  const [source, setSource] = useState<Source | null>(null);

  useEffect(() => {
    (async () => {
      const [p, b] = await Promise.all([
        getRun(brandId, sourceId, runId) as Promise<RunPayload>,
        getBrand(brandId),
      ]);
      setPayload(p);
      setSource(b.sources.find((s) => s.id === sourceId) ?? null);
    })();
  }, [brandId, sourceId, runId]);

  if (!payload || !source)
    return <p className="text-sm text-muted-fg">Loading…</p>;

  const productCount =
    typeof payload._meta.product_count === "number"
      ? payload._meta.product_count
      : payload.records.length;

  return (
    <div className="space-y-4 max-w-none">
      <div className="flex justify-between items-center">
        <div className="text-sm text-muted-fg">
          {productCount} products · status {payload._status}
        </div>
        <button
          onClick={() =>
            downloadCsv(payload.records, `${brandId}-${sourceId}-${runId}.csv`)
          }
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-foreground/50 hover:text-foreground/80 hover:bg-muted/60 transition-colors"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M8 2v8m0 0L5 7.5M8 10l3-2.5" />
            <path d="M3 11v2.5h10V11" />
          </svg>
          Export CSV
        </button>
      </div>
      {source.platform === "official_site" ? (
        isLegacyOfficialSitePayload(payload.records) ? (
          <LegacyOfficialSiteNotice />
        ) : (
          <SnapshotTable
            products={payload.records as ProductRecord[]}
            columns={officialSiteColumns}
          />
        )
      ) : (
        <SnapshotTable
          products={payload.records as ProductRecord[]}
          columns={shopeeColumns}
        />
      )}
    </div>
  );
}

function downloadCsv(records: unknown[], filename: string) {
  const csv = toCsv(records as ProductRecord[]);
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function toCsv(records: ProductRecord[]): string {
  const header = [
    "Category",
    "Name",
    "URL",
    "Image URL",
    "Price",
    "MRP",
    "Currency",
    "Discount %",
    "Sold Out",
    "Item ID",
    "Rating",
    "Sold",
    "Scraped At",
  ].join(",");
  const rows = records.map((p) =>
    [
      csvEscape(p.category ?? ""),
      csvEscape(p.product_name),
      csvEscape(p.product_url ?? ""),
      csvEscape(p.image_url ?? ""),
      p.price ?? "",
      p.mrp ?? "",
      p.currency,
      p.discount_pct ?? "",
      p.is_sold_out ? "true" : "false",
      p.item_id ?? "",
      p.rating_star ?? "",
      p.historical_sold_count ?? "",
      p.scraped_at,
    ].join(","),
  );
  return [header, ...rows].join("\n");
}

function csvEscape(s: string): string {
  return `"${s.replace(/"/g, '""')}"`;
}

function isLegacyOfficialSitePayload(records: unknown[]): boolean {
  if (records.length === 0) return false;
  const r = records[0] as Record<string, unknown>;
  // Legacy CategoryResult shape: status + products_scanned, no product_name.
  return "status" in r && "products_scanned" in r && !("product_name" in r);
}

function LegacyOfficialSiteNotice() {
  return (
    <div className="rounded-2xl bg-card ring-1 ring-border p-6 text-sm text-muted-fg">
      This run uses the legacy per-category aggregate format. Re-run the source
      to collect per-product data in the new format.
    </div>
  );
}
