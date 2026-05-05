"use client";

import { useEffect, useMemo, useState } from "react";
import {
  deleteEnrichment,
  getBrand,
  getRun,
  getRunLogs,
  getUnifiedTable,
  listEnrichments,
} from "@/lib/api";
import type {
  EnrichmentStartResponse,
  EnrichmentSummary,
  LogEntry,
  Platform,
  Source,
  UnifiedColumn,
  UnifiedTable,
} from "@/types";
import SnapshotTable from "./SnapshotTable";
import LogFeed from "./shell/LogFeed";
import ConfirmDialog from "./shell/ConfirmDialog";
import { RowMenu } from "./shell/RowMenu";
import EnrichmentPanel from "./EnrichmentPanel";
import EnrichmentDetailPanel from "./EnrichmentDetailPanel";

interface RunPayload {
  _status: string;
  _meta: Record<string, unknown>;
  records: unknown[];
}

type IncludeMode = "latest_per_field" | "all";

interface Props {
  brandId: string;
  sourceId: string;
  runId: string;
  onStartEnrichment: (resp: EnrichmentStartResponse) => void;
}

export default function RunView({
  brandId,
  sourceId,
  runId,
  onStartEnrichment,
}: Props) {
  const [payload, setPayload] = useState<RunPayload | null>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [table, setTable] = useState<UnifiedTable | null>(null);
  const [enrichments, setEnrichments] = useState<EnrichmentSummary[]>([]);
  const [include, setInclude] = useState<IncludeMode>("latest_per_field");
  const [panelOpen, setPanelOpen] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);
  const [selectedEnrichmentId, setSelectedEnrichmentId] = useState<string | null>(null);
  const [tableRefreshKey, setTableRefreshKey] = useState(0);
  const [pendingDeleteEnrichment, setPendingDeleteEnrichment] = useState<
    string | null
  >(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [p, b, l] = await Promise.all([
        getRun(brandId, sourceId, runId) as Promise<RunPayload>,
        getBrand(brandId),
        getRunLogs(brandId, sourceId, runId),
      ]);
      if (cancelled) return;
      setPayload(p);
      setSource(b.sources.find((s) => s.id === sourceId) ?? null);
      setLogs(l);
    })();
    return () => {
      cancelled = true;
    };
  }, [brandId, sourceId, runId]);

  useEffect(() => {
    if (payload === null) return;
    let cancelled = false;
    (async () => {
      try {
        const [t, e] = await Promise.all([
          getUnifiedTable(brandId, sourceId, runId, include),
          listEnrichments(brandId, sourceId, runId),
        ]);
        if (cancelled) return;
        setTableError(null);
        setTable(t);
        setEnrichments(e);
      } catch (err) {
        if (cancelled) return;
        setTableError((err as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [payload, brandId, sourceId, runId, include, tableRefreshKey]);

  const platform = (source?.platform ?? null) as Platform | null;
  const canEnrich =
    payload !== null &&
    (payload._status === "ok" || payload._status === "cancelled") &&
    platform !== null &&
    !isLegacyOfficialSitePayload(payload.records);

  const productCount =
    payload === null
      ? 0
      : typeof payload._meta.product_count === "number"
        ? payload._meta.product_count
        : payload.records.length;

  const enrichmentCount = useMemo(
    () => enrichments.filter((e) => e.status !== "in_progress").length,
    [enrichments],
  );

  async function handleConfirmDeleteEnrichment() {
    if (!pendingDeleteEnrichment) return;
    const enrichmentId = pendingDeleteEnrichment;
    setPendingDeleteEnrichment(null);
    try {
      await deleteEnrichment(brandId, sourceId, runId, enrichmentId);
    } catch (err) {
      alert(`Failed to delete enrichment: ${(err as Error).message}`);
      return;
    }
    setTableRefreshKey((k) => k + 1);
  }

  if (!payload || !source)
    return <p className="text-sm text-muted-fg">Loading…</p>;

  const legacy = isLegacyOfficialSitePayload(payload.records);

  return (
    <div className="space-y-4 max-w-none">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-muted-fg">
          {productCount} products · status {payload._status}
          {enrichmentCount > 0 && (
            <>
              {" · "}
              {enrichmentCount} enrichment{enrichmentCount === 1 ? "" : "s"}
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          {enrichments.length > 0 && (
            <EnrichmentsMenu
              enrichments={enrichments}
              include={include}
              onIncludeChange={setInclude}
              onDelete={(id) => setPendingDeleteEnrichment(id)}
              onSelect={setSelectedEnrichmentId}
            />
          )}
          {canEnrich && (
            <button
              onClick={() => setPanelOpen(true)}
              className="flex items-center gap-1.5 rounded-lg bg-accent/10 text-accent px-3 py-1.5 text-xs font-medium hover:bg-accent/20 transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M8 3v10M3 8h10" />
              </svg>
              Enrich
            </button>
          )}
          {table && (
            <button
              onClick={() =>
                downloadCsv(table, `${brandId}-${sourceId}-${runId}.csv`)
              }
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-foreground/50 hover:text-foreground/80 hover:bg-muted/60 transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M8 2v8m0 0L5 7.5M8 10l3-2.5" />
                <path d="M3 11v2.5h10V11" />
              </svg>
              Export CSV
            </button>
          )}
        </div>
      </div>

      {legacy && <LegacyOfficialSiteNotice />}

      {!legacy && tableError && (
        <p className="text-sm text-danger-fg bg-danger/10 rounded-lg px-3 py-2">
          {tableError}
        </p>
      )}

      {!legacy && table && (
        <SnapshotTable rows={table.rows} columns={table.columns} interactive />
      )}

      {logs.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground/50 uppercase tracking-wider">
            Logs
          </h3>
          <LogFeed logs={logs} streaming={false} />
        </div>
      )}

      {panelOpen && platform && (
        <EnrichmentPanel
          brandId={brandId}
          sourceId={sourceId}
          runId={runId}
          platform={platform}
          productCount={productCount}
          onClose={() => setPanelOpen(false)}
          onStarted={(resp) => {
            setPanelOpen(false);
            onStartEnrichment(resp);
          }}
        />
      )}

      {selectedEnrichmentId &&
        (() => {
          const summary = enrichments.find(
            (e) => e.id === selectedEnrichmentId,
          );
          if (!summary) return null;
          return (
            <EnrichmentDetailPanel
              brandId={brandId}
              sourceId={sourceId}
              runId={runId}
              summary={summary}
              onClose={() => setSelectedEnrichmentId(null)}
            />
          );
        })()}

      {pendingDeleteEnrichment && (
        <ConfirmDialog
          title="Delete enrichment?"
          body={
            <>
              This will permanently delete this enrichment pass. This cannot be
              undone.
            </>
          }
          confirmLabel="Delete"
          onCancel={() => setPendingDeleteEnrichment(null)}
          onConfirm={handleConfirmDeleteEnrichment}
        />
      )}
    </div>
  );
}

function EnrichmentsMenu({
  enrichments,
  include,
  onIncludeChange,
  onDelete,
  onSelect,
}: {
  enrichments: EnrichmentSummary[];
  include: IncludeMode;
  onIncludeChange: (v: IncludeMode) => void;
  onDelete: (id: string) => void;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const count = enrichments.length;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-foreground/60 hover:text-foreground/80 hover:bg-muted/60 transition-colors ring-1 ring-border"
      >
        Enrichments ({count})
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M2 4l3 3 3-3" />
        </svg>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-20 min-w-72 rounded-xl bg-card ring-1 ring-border shadow-lg overflow-hidden">
            <div className="px-3 py-2 border-b border-border">
              <span className="text-xs uppercase tracking-wider text-muted-fg">
                Show columns
              </span>
              <div className="mt-1.5 flex gap-1">
                <ModeChip
                  active={include === "latest_per_field"}
                  onClick={() => onIncludeChange("latest_per_field")}
                  label="Latest"
                />
                <ModeChip
                  active={include === "all"}
                  onClick={() => onIncludeChange("all")}
                  label="All"
                />
              </div>
            </div>
            <ul className="max-h-72 overflow-y-auto divide-y divide-border">
              {enrichments.map((e) => (
                <li
                  key={e.id}
                  className="group flex items-center gap-2 pr-2 hover:bg-muted/60 transition-colors"
                >
                  <button
                    type="button"
                    onClick={() => {
                      setOpen(false);
                      onSelect(e.id);
                    }}
                    className="flex-1 min-w-0 px-3 py-2 text-xs text-left"
                  >
                    <div
                      className="font-mono text-[11px] text-foreground/80 truncate"
                      title={e.id}
                    >
                      {e.id}
                    </div>
                    <div className="text-muted-fg">
                      {e.status}
                      {typeof e.aggregates.products_enriched === "number" && (
                        <> · {e.aggregates.products_enriched} enriched</>
                      )}
                      {typeof e.aggregates.products_failed === "number" &&
                        e.aggregates.products_failed > 0 && (
                          <span className="text-pink-700">
                            {" · "}
                            {e.aggregates.products_failed} failed
                          </span>
                        )}
                    </div>
                  </button>
                  <div className="shrink-0">
                    <RowMenu
                      ariaLabel="Enrichment actions"
                      items={[
                        {
                          label: "Delete",
                          destructive: true,
                          onSelect: () => {
                            setOpen(false);
                            onDelete(e.id);
                          },
                        },
                      ]}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}

function ModeChip({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
        active
          ? "bg-accent-soft text-accent ring-1 ring-accent/30"
          : "bg-muted text-foreground/60 hover:bg-muted/80"
      }`}
    >
      {label}
    </button>
  );
}

function downloadCsv(table: UnifiedTable, filename: string) {
  const csv = toCsv(table);
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function toCsv(table: UnifiedTable): string {
  // CSV surfaces all columns (including ones hidden in the UI like scraped_at
  // and mrp/currency) so the export is lossless.
  const cols: UnifiedColumn[] = table.columns;
  const header = cols.map((c) => csvEscape(c.label)).join(",");
  const lines = table.rows.map((row) =>
    cols.map((c) => csvEscape(csvValue(row[c.id]))).join(","),
  );
  return [header, ...lines].join("\n");
}

function csvValue(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.join("; ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function csvEscape(s: string): string {
  return `"${s.replace(/"/g, '""')}"`;
}

function isLegacyOfficialSitePayload(records: unknown[]): boolean {
  if (records.length === 0) return false;
  const r = records[0] as Record<string, unknown>;
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
