"use client";

import { useState } from "react";
import { createSource, updateSource } from "@/lib/api";
import type { Platform, Source } from "@/types";
import OfficialSiteAddSourceForm from "./platforms/official_site/AddSourceForm";
import ShopeeAddSourceForm from "./platforms/shopee/AddSourceForm";
import { formatPlatform } from "@/lib/format";

export default function AddSourceDrawer({
  open,
  onClose,
  brandId,
  sources,
  editingSource,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  brandId: string;
  sources: Source[];
  editingSource?: Source | null;
  onCreated: () => void;
}) {
  const [platform, setPlatform] = useState<Platform>("official_site");
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const isEditing = !!editingSource;
  const activePlatform: Platform = editingSource?.platform ?? platform;
  const initialSpec = editingSource?.spec as
    | Record<string, unknown>
    | undefined;

  async function submit(spec: Record<string, unknown>) {
    setError(null);
    try {
      if (editingSource) {
        await updateSource(brandId, editingSource.id, spec);
      } else {
        await createSource(brandId, activePlatform, spec);
      }
      onCreated();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : isEditing
            ? "Failed to update source"
            : "Failed to add source",
      );
    }
  }

  // Force form remount when switching between sources so initialSpec is re-read
  const formKey = editingSource?.id ?? `new-${activePlatform}`;

  return (
    <div className="fixed inset-0 bg-black/30 flex items-start justify-center z-50 pt-20">
      <div className="bg-card rounded-2xl ring-1 ring-border p-6 w-[min(90vw,640px)] space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider">
            {isEditing ? "Edit source" : "Add source"}
          </h2>
          <button
            onClick={onClose}
            className="text-foreground/50 hover:text-foreground/80"
          >
            ×
          </button>
        </div>

        {isEditing ? (
          <div className="text-xs text-muted-fg uppercase tracking-wider">
            {formatPlatform(activePlatform)}
          </div>
        ) : (
          <div className="flex gap-2">
            {(["official_site", "shopee"] as Platform[]).map((p) => (
              <button
                key={p}
                onClick={() => setPlatform(p)}
                className={`px-3 py-1.5 text-sm rounded-xl ${
                  platform === p
                    ? "bg-accent text-white"
                    : "bg-foreground/5 text-foreground/60"
                }`}
              >
                {formatPlatform(p)}
              </button>
            ))}
          </div>
        )}

        {activePlatform === "official_site" ? (
          <OfficialSiteAddSourceForm
            key={formKey}
            brandId={brandId}
            sources={sources}
            onSubmit={submit}
            initialSpec={initialSpec}
            submitLabel={isEditing ? "Save changes" : "Add source"}
          />
        ) : (
          <ShopeeAddSourceForm
            key={formKey}
            onSubmit={submit}
            initialSpec={initialSpec}
            submitLabel={isEditing ? "Save changes" : "Add source"}
          />
        )}

        {error && <p className="text-sm text-danger-fg">{error}</p>}
      </div>
    </div>
  );
}
