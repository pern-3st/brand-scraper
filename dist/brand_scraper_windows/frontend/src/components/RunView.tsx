"use client";

import { useEffect, useState } from "react";
import { getRun, getBrand } from "@/lib/api";
import type { CategoryResult, ShopeeProductRecord, Source } from "@/types";
import OfficialSiteSnapshotTable from "./platforms/official_site/SnapshotTable";
import ShopeeSnapshotTable from "./platforms/shopee/SnapshotTable";

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
            downloadCsv(
              source.platform,
              payload.records,
              `${brandId}-${sourceId}-${runId}.csv`
            )
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
        <OfficialSiteSnapshotTable
          brand={String(source.spec.brand_url ?? "")}
          section={String(source.spec.section ?? "")}
          results={payload.records as CategoryResult[]}
        />
      ) : (
        <ShopeeSnapshotTable
          products={payload.records as ShopeeProductRecord[]}
        />
      )}
    </div>
  );
}

function downloadCsv(
  platform: Source["platform"],
  records: unknown[],
  filename: string
) {
  const csv =
    platform === "official_site"
      ? toOfficialSiteCsv(records as CategoryResult[])
      : toShopeeCsv(records as ShopeeProductRecord[]);
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function toOfficialSiteCsv(results: CategoryResult[]): string {
  const header =
    "Category,Status,Lowest Price,Highest Price,Products Scanned";
  const rows = results.map(
    (r) =>
      `"${r.category}",${r.status},${r.lowest_price ?? ""},${r.highest_price ?? ""},${r.products_scanned}`
  );
  return [header, ...rows].join("\n");
}

function toShopeeCsv(products: ShopeeProductRecord[]): string {
  const header = [
    "Item ID",
    "Name",
    "URL",
    "Price",
    "MRP",
    "Currency",
    "Discount %",
    "Rating",
    "Sold",
    "Sold Out",
    "Scraped At",
  ].join(",");
  const rows = products.map((p) =>
    [
      p.item_id,
      csvEscape(p.product_name),
      csvEscape(p.product_url),
      p.price ?? "",
      p.mrp ?? "",
      p.currency,
      p.discount_pct ?? "",
      p.rating_star ?? "",
      p.historical_sold_count ?? "",
      p.is_sold_out ? "true" : "false",
      p.scraped_at,
    ].join(",")
  );
  return [header, ...rows].join("\n");
}

function csvEscape(s: string): string {
  return `"${s.replace(/"/g, '""')}"`;
}
