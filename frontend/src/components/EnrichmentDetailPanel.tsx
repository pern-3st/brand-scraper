"use client";

import { useEffect, useState } from "react";
import { getEnrichment, getEnrichmentLogs } from "@/lib/api";
import type { EnrichmentSummary, LogEntry } from "@/types";
import LogFeed from "./shell/LogFeed";

interface EnrichmentPayload {
  _status?: string;
  _meta?: {
    request?: {
      curated_fields?: string[];
      freeform_prompts?: { id: string; label: string; prompt: string }[];
    };
    aggregates?: Record<string, number | null>;
  };
  results?: {
    product_key: string;
    values: Record<string, unknown>;
    errors: Record<string, string>;
    enriched_at: string;
  }[];
}

interface Props {
  brandId: string;
  sourceId: string;
  runId: string;
  summary: EnrichmentSummary;
  onClose: () => void;
}

export default function EnrichmentDetailPanel({
  brandId,
  sourceId,
  runId,
  summary,
  onClose,
}: Props) {
  const [payload, setPayload] = useState<EnrichmentPayload | null>(null);
  const [logs, setLogs] = useState<LogEntry[] | null>(null);
  const [showAllFailures, setShowAllFailures] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [p, l] = await Promise.all([
        getEnrichment(brandId, sourceId, runId, summary.id).catch(() => null),
        summary.status === "in_progress"
          ? Promise.resolve(null)
          : getEnrichmentLogs(brandId, sourceId, runId, summary.id).catch(
              () => [] as LogEntry[],
            ),
      ]);
      if (cancelled) return;
      setPayload(p as EnrichmentPayload | null);
      setLogs(l);
    })();
    return () => {
      cancelled = true;
    };
  }, [brandId, sourceId, runId, summary.id, summary.status]);

  const aggs = summary.aggregates ?? {};
  const attempted = numOrDash(aggs.products_attempted);
  const enriched = numOrDash(aggs.products_enriched);
  const failed = numOrDash(aggs.products_failed);
  const skipped = numOrDash(aggs.products_skipped_no_key);

  const curated =
    payload?._meta?.request?.curated_fields ?? summary.request?.curated_fields ?? [];
  const freeform =
    payload?._meta?.request?.freeform_prompts ??
    summary.request?.freeform_prompts ??
    [];
  const failedRows = (payload?.results ?? []).filter(
    (r) => r.errors && Object.keys(r.errors).length > 0,
  );
  const shownFailures = showAllFailures ? failedRows : failedRows.slice(0, 10);

  return (
    <>
      <div
        className="fixed inset-0 z-30 bg-black/30"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className="fixed right-0 top-0 z-40 h-full w-[480px] max-w-[90vw] bg-card ring-1 ring-border shadow-xl overflow-y-auto"
        role="dialog"
        aria-label="Enrichment detail"
      >
        <header className="flex items-start justify-between gap-3 px-4 py-3 border-b border-border">
          <div className="min-w-0">
            <div
              className="font-mono text-xs text-foreground/80 truncate"
              title={summary.id}
            >
              {summary.id}
            </div>
            <div className="mt-0.5 text-xs">
              <StatusChip status={summary.status} />
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-foreground/40 hover:text-foreground/80"
            aria-label="Close detail panel"
          >
            ×
          </button>
        </header>

        <section className="grid grid-cols-4 gap-2 px-4 py-3 border-b border-border">
          <StatTile label="Attempted" value={attempted} />
          <StatTile label="Enriched" value={enriched} />
          <StatTile
            label="Failed"
            value={failed}
            tone={Number(failed) > 0 ? "pink" : undefined}
          />
          <StatTile label="Skipped" value={skipped} tone="muted" />
        </section>

        {(curated.length > 0 || freeform.length > 0) && (
          <section className="px-4 py-3 border-b border-border">
            <h4 className="text-[11px] uppercase tracking-wider text-muted-fg mb-1.5">
              Requested fields
            </h4>
            <div className="flex flex-wrap gap-1">
              {curated.map((f) => (
                <Chip key={f}>{f}</Chip>
              ))}
              {freeform.map((f) => (
                <Chip key={f.id}>
                  {f.label} <span className="text-muted-fg">(freeform)</span>
                </Chip>
              ))}
            </div>
          </section>
        )}

        {failedRows.length > 0 && (
          <section className="px-4 py-3 border-b border-border">
            <h4 className="text-[11px] uppercase tracking-wider text-muted-fg mb-1.5">
              Failures ({failedRows.length})
            </h4>
            <ul className="space-y-1.5 text-xs">
              {shownFailures.map((row) => (
                <li key={row.product_key} className="text-foreground/80">
                  <div
                    className="font-mono text-[11px] truncate"
                    title={row.product_key}
                  >
                    {row.product_key}
                  </div>
                  <div className="text-pink-700 break-words">
                    {firstErrorMessage(row.errors)}
                  </div>
                </li>
              ))}
            </ul>
            {failedRows.length > 10 && (
              <button
                onClick={() => setShowAllFailures((v) => !v)}
                className="mt-2 text-xs text-accent hover:underline"
              >
                {showAllFailures
                  ? "Show fewer"
                  : `Show all ${failedRows.length}`}
              </button>
            )}
          </section>
        )}

        <section className="px-4 py-3">
          <h4 className="text-[11px] uppercase tracking-wider text-muted-fg mb-1.5">
            Logs
          </h4>
          {summary.status === "in_progress" ? (
            <p className="text-xs text-muted-fg">
              Pass is still running — open the live progress view for updates.
            </p>
          ) : logs === null ? (
            <p className="text-xs text-muted-fg">Loading logs…</p>
          ) : logs.length === 0 ? (
            <p className="text-xs text-muted-fg">
              No log entries were written for this pass.
            </p>
          ) : (
            <LogFeed logs={logs} streaming={false} />
          )}
        </section>
      </aside>
    </>
  );
}

function StatTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "pink" | "muted";
}) {
  const valueClass =
    tone === "pink"
      ? "text-pink-700"
      : tone === "muted"
        ? "text-foreground/50"
        : "text-foreground";
  return (
    <div className="rounded-lg bg-muted/40 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wider text-muted-fg">
        {label}
      </div>
      <div className={`mt-0.5 text-sm font-semibold tabular-nums ${valueClass}`}>
        {value}
      </div>
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  const cls =
    status === "ok"
      ? "bg-emerald-500/10 text-emerald-700"
      : status === "error"
        ? "bg-pink-500/10 text-pink-700"
        : status === "cancelled"
          ? "bg-amber-500/10 text-amber-700"
          : "bg-muted text-foreground/60";
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}
    >
      {status}
    </span>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-[11px] text-foreground/70">
      {children}
    </span>
  );
}

function numOrDash(v: number | null | undefined): string {
  return typeof v === "number" ? String(v) : "–";
}

function firstErrorMessage(errors: Record<string, string>): string {
  const key = "_all" in errors ? "_all" : Object.keys(errors)[0];
  return key ? errors[key] : "";
}
