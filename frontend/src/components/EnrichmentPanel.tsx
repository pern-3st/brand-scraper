"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getEnrichmentFields,
  getEnrichmentHistory,
  startEnrichment,
} from "@/lib/api";
import type {
  EnrichmentRequest,
  EnrichmentStartResponse,
  FieldDef,
  FreeformPrompt,
  Platform,
  SavedFreeformPrompt,
} from "@/types";

interface Props {
  brandId: string;
  sourceId: string;
  runId: string;
  platform: Platform;
  productCount: number;
  onStarted: (resp: EnrichmentStartResponse) => void;
  onClose: () => void;
}

interface FreeformDraft {
  localId: string;
  label: string;
  prompt: string;
}

// ~10s per product is a coarse-but-honest heuristic — matches the one-shot
// extract call against the product page on the LLM-backed path. Shopee's DOM
// path is faster, but we under-promise.
const SECONDS_PER_PRODUCT = 10;

export default function EnrichmentPanel({
  brandId,
  sourceId,
  runId,
  platform,
  productCount,
  onStarted,
  onClose,
}: Props) {
  const [catalog, setCatalog] = useState<FieldDef[] | null>(null);
  const [supportsFreeform, setSupportsFreeform] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [freeform, setFreeform] = useState<FreeformDraft[]>([]);
  const [savedPrompts, setSavedPrompts] = useState<SavedFreeformPrompt[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getEnrichmentFields(platform),
      getEnrichmentHistory(brandId, platform).catch(() => null),
    ])
      .then(([fields, history]) => {
        if (cancelled) return;
        setCatalog(fields.fields);
        setSupportsFreeform(fields.supports_freeform);
        if (history) {
          setSavedPrompts(history.saved_prompts);
          if (history.most_recent) {
            // Filter curated to the platform's current catalog so renamed/
            // removed field ids don't get sent in a future request.
            const knownIds = new Set(fields.fields.map((f) => f.id));
            setSelected(
              new Set(
                history.most_recent.curated_fields.filter((id) => knownIds.has(id))
              )
            );
            if (fields.supports_freeform) {
              setFreeform(
                history.most_recent.freeform_prompts.map((p) => ({
                  localId: crypto.randomUUID(),
                  label: p.label,
                  prompt: p.prompt,
                }))
              );
            }
          }
        }
      })
      .catch((e) => setError(`Failed to load fields: ${(e as Error).message}`));
    return () => {
      cancelled = true;
    };
  }, [platform, brandId]);

  const grouped = useMemo(() => {
    if (!catalog) return new Map<string, FieldDef[]>();
    const m = new Map<string, FieldDef[]>();
    for (const f of catalog) {
      const key = f.category ?? "general";
      const list = m.get(key) ?? [];
      list.push(f);
      m.set(key, list);
    }
    return m;
  }, [catalog]);

  const selectedCount = selected.size + freeform.filter((f) => f.label.trim()).length;
  const estimateSeconds = productCount * SECONDS_PER_PRODUCT;

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAll() {
    if (!catalog) return;
    setSelected(new Set(catalog.map((f) => f.id)));
  }

  function clearAll() {
    setSelected(new Set());
  }

  function addFreeform() {
    setFreeform((prev) => [
      ...prev,
      { localId: crypto.randomUUID(), label: "", prompt: "" },
    ]);
  }

  function addSavedPrompt(saved: SavedFreeformPrompt) {
    setFreeform((prev) => [
      ...prev,
      { localId: crypto.randomUUID(), label: saved.label, prompt: saved.prompt },
    ]);
  }

  function updateFreeform(localId: string, patch: Partial<FreeformDraft>) {
    setFreeform((prev) =>
      prev.map((f) => (f.localId === localId ? { ...f, ...patch } : f))
    );
  }

  function removeFreeform(localId: string) {
    setFreeform((prev) => prev.filter((f) => f.localId !== localId));
  }

  async function handleStart() {
    setError(null);
    const prompts: FreeformPrompt[] = freeform
      .filter((f) => f.label.trim() && f.prompt.trim())
      .map((f) => ({
        // Server sanitises + collision-checks — we send the raw label as id.
        id: f.label.trim(),
        label: f.label.trim(),
        prompt: f.prompt.trim(),
      }));

    const req: EnrichmentRequest = {
      curated_fields: [...selected],
      freeform_prompts: prompts,
    };

    if (req.curated_fields.length === 0 && req.freeform_prompts.length === 0) {
      setError("Select at least one field or add one question.");
      return;
    }

    setSubmitting(true);
    try {
      const resp = await startEnrichment(brandId, sourceId, runId, req);
      onStarted(resp);
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={onClose}>
      <div
        className="h-full w-full max-w-lg bg-card shadow-xl ring-1 ring-border overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between gap-4 px-6 py-4 bg-card/95 backdrop-blur border-b border-border">
          <div>
            <h2 className="text-base font-semibold">Enrich products</h2>
            <p className="text-xs text-muted-fg mt-0.5">
              {productCount} products · est. ~{formatDuration(estimateSeconds)}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-foreground/40 hover:text-foreground/80 transition-colors"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <path d="M5 5l10 10M15 5L5 15" />
            </svg>
          </button>
        </div>

        <div className="px-6 py-6 space-y-8">
          {catalog === null && !error && (
            <p className="text-sm text-muted-fg">Loading fields…</p>
          )}

          {catalog && (
            <section className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-foreground/70">
                  Curated fields
                </span>
                <div className="flex gap-3 text-xs">
                  <button
                    type="button"
                    onClick={selectAll}
                    className="text-accent hover:text-accent-hover transition-colors"
                  >
                    Select all
                  </button>
                  <button
                    type="button"
                    onClick={clearAll}
                    className="text-accent hover:text-accent-hover transition-colors"
                  >
                    Clear
                  </button>
                </div>
              </div>
              {catalog.length === 0 ? (
                <p className="text-sm text-muted-fg">
                  No curated fields available for this platform.
                </p>
              ) : (
                [...grouped.entries()].map(([group, fields]) => (
                  <div key={group} className="space-y-2">
                    <span className="text-xs uppercase tracking-wider text-muted-fg">
                      {group}
                    </span>
                    <div className="flex flex-wrap gap-2">
                      {fields.map((f) => {
                        const isSel = selected.has(f.id);
                        return (
                          <button
                            key={f.id}
                            type="button"
                            onClick={() => toggle(f.id)}
                            title={f.description}
                            className={`rounded-full px-4 py-1.5 text-sm transition-colors ${
                              isSel
                                ? "bg-accent-soft text-accent font-medium ring-1 ring-accent/30"
                                : "bg-muted text-foreground/60 hover:bg-muted/80"
                            }`}
                          >
                            {isSel && (
                              <span className="mr-1.5" aria-hidden>
                                &#10003;
                              </span>
                            )}
                            {f.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))
              )}
            </section>
          )}

          {supportsFreeform && (
            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-foreground/70">
                  Custom questions
                </span>
                <button
                  type="button"
                  onClick={addFreeform}
                  className="text-xs text-accent hover:text-accent-hover transition-colors"
                >
                  + Add a question
                </button>
              </div>
              <p className="text-xs text-muted-fg">
                Ask free-form questions about each product. The column label
                becomes the field id (e.g. &quot;Is vegan?&quot;).
              </p>
              {savedPrompts.length > 0 && (
                <div className="space-y-2">
                  <span className="text-xs uppercase tracking-wider text-muted-fg">
                    Saved for this brand
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {savedPrompts.map((sp) => {
                      const inUse = freeform.some(
                        (f) => f.label.trim() === sp.label.trim()
                      );
                      return (
                        <button
                          key={sp.id}
                          type="button"
                          onClick={() => addSavedPrompt(sp)}
                          disabled={inUse}
                          title={sp.prompt}
                          className={`rounded-full px-3 py-1 text-xs transition-colors ${
                            inUse
                              ? "bg-muted/40 text-muted-fg cursor-not-allowed"
                              : "bg-muted text-foreground/70 hover:bg-muted/80"
                          }`}
                        >
                          {inUse ? "✓ " : "+ "}
                          {sp.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              <div className="space-y-3">
                {freeform.map((f) => (
                  <div
                    key={f.localId}
                    className="rounded-xl bg-muted/40 ring-1 ring-border p-3 space-y-2"
                  >
                    <div className="flex items-start gap-2">
                      <input
                        type="text"
                        placeholder="Column label (e.g. Is vegan?)"
                        value={f.label}
                        onChange={(e) =>
                          updateFreeform(f.localId, { label: e.target.value })
                        }
                        className="flex-1 rounded-lg bg-card px-3 py-2 text-sm ring-1 ring-border focus:outline-none focus:ring-accent"
                      />
                      <button
                        type="button"
                        onClick={() => removeFreeform(f.localId)}
                        aria-label="Remove question"
                        className="px-2 py-2 text-foreground/40 hover:text-danger-fg transition-colors"
                      >
                        ×
                      </button>
                    </div>
                    <textarea
                      placeholder="Prompt sent to the model (e.g. Does this product contain animal-derived ingredients?)"
                      value={f.prompt}
                      onChange={(e) =>
                        updateFreeform(f.localId, { prompt: e.target.value })
                      }
                      rows={2}
                      className="w-full rounded-lg bg-card px-3 py-2 text-sm ring-1 ring-border focus:outline-none focus:ring-accent resize-none"
                    />
                  </div>
                ))}
              </div>
            </section>
          )}

          {error && (
            <p className="text-sm text-danger-fg bg-danger/10 rounded-lg px-3 py-2">
              {error}
            </p>
          )}
        </div>

        <div className="sticky bottom-0 bg-card/95 backdrop-blur border-t border-border px-6 py-4 flex items-center justify-between gap-4">
          <span className="text-xs text-muted-fg">
            {selectedCount} field{selectedCount === 1 ? "" : "s"} selected
          </span>
          <button
            onClick={handleStart}
            disabled={submitting || selectedCount === 0}
            className="rounded-xl bg-accent px-5 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:bg-muted disabled:text-muted-fg disabled:cursor-not-allowed"
          >
            {submitting ? "Starting…" : "Start enrichment"}
          </button>
        </div>
      </div>
    </div>
  );
}

function formatDuration(totalSeconds: number): string {
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const mins = Math.round(totalSeconds / 60);
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}
