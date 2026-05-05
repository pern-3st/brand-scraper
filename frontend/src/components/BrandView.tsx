"use client";

import { useEffect, useState } from "react";
import { deleteRun, getBrand, listRuns } from "@/lib/api";
import type { BrandDetail, RunSummary, Source } from "@/types";
import AddSourceDrawer from "./AddSourceDrawer";
import { formatPlatform } from "@/lib/format";

export default function BrandView({
  brandId,
  onOpenRun,
  onStartScrape,
}: {
  brandId: string;
  onOpenRun: (sourceId: string, runId: string) => void;
  onStartScrape: (sourceId: string) => void | Promise<void>;
}) {
  const [detail, setDetail] = useState<BrandDetail | null>(null);
  const [runsBySource, setRunsBySource] = useState<Record<string, RunSummary[]>>(
    {}
  );
  const [adding, setAdding] = useState(false);
  const [editingSource, setEditingSource] = useState<Source | null>(null);

  async function reload() {
    const d = await getBrand(brandId);
    setDetail(d);
    const runs: Record<string, RunSummary[]> = {};
    for (const s of d.sources) runs[s.id] = await listRuns(brandId, s.id);
    setRunsBySource(runs);
  }
  useEffect(() => {
    reload();
  }, [brandId]);

  if (!detail) return <p className="text-sm text-muted-fg">Loading…</p>;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{detail.name}</h1>
      </div>

      {detail.sources.length === 0 && (
        <div className="rounded-2xl bg-card ring-1 ring-border p-8 text-center space-y-4">
          <p className="text-muted-fg">No sources yet.</p>
          <button
            onClick={() => setAdding(true)}
            className="rounded-xl bg-accent px-4 py-2 text-sm text-white hover:bg-accent-hover"
          >
            + Add source
          </button>
        </div>
      )}

      {detail.sources.map((source) => (
        <SourceCard
          key={source.id}
          source={source}
          runs={runsBySource[source.id] ?? []}
          onStartScrape={() => onStartScrape(source.id)}
          onOpenRun={(runId) => onOpenRun(source.id, runId)}
          onEdit={() => setEditingSource(source)}
          onDeleteRun={async (runId) => {
            if (!confirm("Delete this run? This cannot be undone.")) return;
            try {
              await deleteRun(brandId, source.id, runId);
            } catch (err) {
              alert(`Failed to delete run: ${err instanceof Error ? err.message : String(err)}`);
              return;
            }
            await reload();
          }}
        />
      ))}

      {detail.sources.length > 0 && (
        <button
          onClick={() => setAdding(true)}
          className="text-sm text-foreground/50 hover:text-foreground/80"
        >
          + Add source
        </button>
      )}

      <AddSourceDrawer
        open={adding || editingSource !== null}
        brandId={brandId}
        sources={detail.sources}
        editingSource={editingSource}
        onClose={() => {
          setAdding(false);
          setEditingSource(null);
        }}
        onCreated={async () => {
          setAdding(false);
          setEditingSource(null);
          await reload();
        }}
      />
    </div>
  );
}

function SourceCard({
  source,
  runs,
  onStartScrape,
  onOpenRun,
  onEdit,
  onDeleteRun,
}: {
  source: Source;
  runs: RunSummary[];
  onStartScrape: () => void;
  onOpenRun: (runId: string) => void;
  onEdit: () => void;
  onDeleteRun: (runId: string) => void | Promise<void>;
}) {
  const [showAll, setShowAll] = useState(false);
  const latest = runs[0] ?? null;
  const isRunning = latest?.status === "in_progress";
  const visibleRuns = showAll ? runs : runs.slice(0, 3);

  return (
    <section className="rounded-2xl bg-card ring-1 ring-border p-6 space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1 min-w-0">
          <h2 className="text-lg font-semibold text-foreground truncate">
            {source.name}
          </h2>
          <div className="text-xs text-muted-fg uppercase tracking-wider truncate">
            {formatPlatform(source.platform)} · {primaryUrl(source)}
          </div>
        </div>
        <button
          onClick={onEdit}
          className="text-xs text-foreground/50 hover:text-foreground/80 uppercase tracking-wider shrink-0"
        >
          Edit
        </button>
      </div>

      {configRows(source).length > 0 && (
        <div className="border-t border-border pt-4">
          <ConfigurationRows source={source} />
        </div>
      )}

      {/* Recent runs */}
      <div className="border-t border-border pt-4">
        {runs.length === 0 ? (
          <div className="flex justify-center">
            <button
              onClick={onStartScrape}
              disabled={isRunning}
              className="rounded-xl bg-accent px-4 py-2 text-sm text-white hover:bg-accent-hover disabled:opacity-40"
            >
              Scrape now
            </button>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-foreground/50 uppercase tracking-wider">
                Recent runs
              </h3>
              <button
                onClick={onStartScrape}
                disabled={isRunning}
                className="rounded-xl bg-accent px-4 py-2 text-sm text-white hover:bg-accent-hover disabled:opacity-40"
              >
                Scrape now
              </button>
            </div>
            <ul className="divide-y divide-border">
              {visibleRuns.map((run) => (
                <li
                  key={run.id}
                  className="group flex items-center gap-4 py-2 text-sm hover:bg-foreground/[0.02]"
                >
                  <button
                    onClick={() => onOpenRun(run.id)}
                    className="flex items-center gap-4 flex-1 min-w-0 text-left"
                  >
                    <span className="text-foreground/80 shrink-0 w-16">
                      {formatRunDate(run.id)}
                    </span>
                    <span className="text-muted-fg shrink-0 w-24">
                      {statusLabel(run.status)}
                    </span>
                    <span className="text-muted-fg flex-1 truncate">
                      {run.aggregates.product_count != null
                        ? `${run.aggregates.product_count} products`
                        : "—"}
                    </span>
                  </button>
                  <button
                    onClick={() => onDeleteRun(run.id)}
                    aria-label="Delete run"
                    className="text-xs text-foreground/40 hover:text-red-500 uppercase tracking-wider shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
            {runs.length > 3 && !showAll && (
              <button
                onClick={() => setShowAll(true)}
                className="mt-2 text-xs text-foreground/50 hover:text-foreground/80 uppercase tracking-wider"
              >
                Show all ({runs.length})
              </button>
            )}
          </>
        )}
      </div>
    </section>
  );
}

function configRows(source: Source): Array<[string, string]> {
  const rows: Array<[string, string]> = [];
  if (source.platform === "official_site") {
    if (typeof source.spec.section === "string") {
      rows.push(["Section", source.spec.section]);
    }
    if (Array.isArray(source.spec.categories)) {
      const cats = (source.spec.categories as unknown[])
        .filter((c): c is string => typeof c === "string");
      if (cats.length > 0) rows.push(["Categories", cats.join(", ")]);
    }
  }
  return rows;
}

function ConfigurationRows({ source }: { source: Source }) {
  const rows = configRows(source);
  return (
    <dl className="space-y-1 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="flex gap-4">
          <dt className="text-muted-fg w-28 shrink-0">{k}</dt>
          <dd className="text-foreground/80 min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function statusLabel(status: string): string {
  switch (status) {
    case "ok":
      return "OK";
    case "error":
      return "Error";
    case "cancelled":
      return "Cancelled";
    case "in_progress":
      return "Running…";
    default:
      return status.charAt(0).toUpperCase() + status.slice(1);
  }
}

function primaryUrl(s: Source): string {
  if (s.platform === "shopee") return String(s.spec.shop_url ?? "");
  if (s.platform === "official_site") return String(s.spec.brand_url ?? "");
  return "";
}

function formatRunDate(runId: string): string {
  const m = runId.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/);
  if (!m) return runId;
  const d = new Date(
    Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6])
  );
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

