"use client";

import { useEffect } from "react";
import { cancelScrape } from "@/lib/api";
import { useEnrichmentStream } from "@/hooks/useEnrichmentStream";
import LogFeed from "./shell/LogFeed";

interface Props {
  sessionId: string;
  onTerminated: () => void;
}

export default function EnrichmentProgress({ sessionId, onTerminated }: Props) {
  const { started, rows, logs, status, error } = useEnrichmentStream(sessionId);

  const isStreaming = status === "connecting" || status === "streaming";
  const isTerminal = status === "done" || status === "cancelled" || status === "error";

  useEffect(() => {
    if (isTerminal) {
      const t = setTimeout(onTerminated, 1200);
      return () => clearTimeout(t);
    }
  }, [isTerminal, onTerminated]);

  const total = started
    ? started.total_products
      - started.products_skipped_no_key
      - (started.products_skipped_already_enriched ?? 0)
    : 0;
  const done = rows.length;
  const pct = total > 0 ? Math.min(100, (done / total) * 100) : 0;

  const statusLabel = (() => {
    if (status === "connecting") return "Connecting…";
    if (status === "streaming") return "Enriching…";
    if (status === "done") return "Complete";
    if (status === "cancelled") return "Cancelled";
    if (status === "error") return "Error";
    return status;
  })();

  const failed = rows.filter((r) => r.errors && "_all" in r.errors).length;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-3 space-y-4">
          <div className="rounded-2xl bg-card p-6 shadow-md shadow-accent/5 ring-1 ring-border">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold">Enriching products</h2>
                <p className="text-sm text-muted-fg mt-1">
                  {started ? (
                    <>
                      {done} of {total} products
                      {failed > 0 && (
                        <span className="text-danger-fg"> · {failed} failed</span>
                      )}
                      {started.products_skipped_no_key > 0 && (
                        <span className="text-muted-fg">
                          {" "}
                          · {started.products_skipped_no_key} skipped
                        </span>
                      )}
                      {(started.products_skipped_already_enriched ?? 0) > 0 && (
                        <span className="text-muted-fg">
                          {" "}
                          · {started.products_skipped_already_enriched} already enriched
                        </span>
                      )}
                    </>
                  ) : (
                    "Waiting to start…"
                  )}
                </p>
                {started && started.requested_fields.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {started.requested_fields.map((f) => (
                      <span
                        key={f}
                        className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs text-foreground/60"
                      >
                        {f}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <span
                className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${
                  status === "done"
                    ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300/50"
                    : status === "cancelled"
                      ? "bg-amber-100 text-amber-800 ring-1 ring-amber-300/50"
                      : status === "error"
                        ? "bg-pink-100 text-pink-600 ring-1 ring-pink-300/50"
                        : "bg-accent-soft text-accent ring-1 ring-accent/30"
                }`}
              >
                {statusLabel}
              </span>
            </div>

            <div className="mt-5 h-2 rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full transition-all duration-500 ${
                  status === "error"
                    ? "bg-danger"
                    : status === "cancelled"
                      ? "bg-amber-400"
                      : "bg-accent"
                }`}
                style={{ width: `${pct}%` }}
              />
            </div>

            {error && (
              <p className="mt-3 text-sm text-danger-fg bg-danger/10 rounded-lg px-3 py-2">
                {error}
              </p>
            )}
          </div>

          <div className="rounded-2xl bg-card ring-1 ring-border overflow-hidden">
            <div className="flex items-center justify-between px-6 py-3 border-b border-border">
              <h3 className="text-sm font-semibold text-foreground/50 uppercase tracking-wider">
                Live rows
              </h3>
              <span className="text-xs text-muted-fg">{rows.length}</span>
            </div>
            <div className="max-h-[420px] overflow-y-auto divide-y divide-border">
              {rows.length === 0 && (
                <p className="px-6 py-8 text-center text-sm text-muted-fg">
                  Waiting for the first row…
                </p>
              )}
              {rows.map((r) => (
                <RowLine key={`${r.product_key}-${r.index}`} row={r} />
              ))}
            </div>
          </div>
        </div>
        <div className="lg:col-span-2">
          <div className="lg:sticky lg:top-6">
            <LogFeed logs={logs} streaming={isStreaming} />
          </div>
        </div>
      </div>

      {isStreaming && (
        <div className="flex justify-center">
          <button
            onClick={() => cancelScrape(sessionId)}
            className="rounded-xl bg-danger/10 text-danger-fg px-6 py-2.5 text-sm font-medium ring-1 ring-danger/30 hover:bg-danger/20"
          >
            Stop enrichment
          </button>
        </div>
      )}
    </div>
  );
}

function RowLine({ row }: { row: { product_key: string; values: Record<string, unknown>; errors: Record<string, string>; index: number } }) {
  const failed = "_all" in row.errors;
  const fieldCount = Object.keys(row.values).length;
  const errCount = Object.keys(row.errors).filter((k) => k !== "_all").length;

  return (
    <div className="px-6 py-2.5 flex items-center justify-between gap-4 text-sm">
      <div className="flex items-center gap-3 min-w-0">
        <span className="text-xs text-muted-fg tabular-nums w-10 shrink-0">
          #{row.index}
        </span>
        <span className="truncate text-foreground/80 font-mono text-xs" title={row.product_key}>
          {row.product_key}
        </span>
      </div>
      <div className="shrink-0">
        {failed ? (
          <span
            className="inline-flex items-center rounded-full bg-pink-100 px-2 py-0.5 text-xs font-medium text-pink-700"
            title={row.errors._all}
          >
            failed
          </span>
        ) : (
          <span className="text-xs text-muted-fg">
            {fieldCount} field{fieldCount === 1 ? "" : "s"}
            {errCount > 0 && (
              <span className="text-pink-700"> · {errCount} err</span>
            )}
          </span>
        )}
      </div>
    </div>
  );
}
