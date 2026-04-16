"use client";

import { useState } from "react";

export default function NewBrandModal({
  open,
  onClose,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  onCreate: (name: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  async function submit() {
    setError(null);
    setSubmitting(true);
    try {
      await onCreate(name.trim());
      setName("");
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create brand");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
      <div className="bg-card rounded-2xl ring-1 ring-border p-6 w-[min(90vw,420px)] space-y-4">
        <h2 className="text-sm font-semibold text-foreground/80 uppercase tracking-wider">
          New brand
        </h2>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Brand name"
          className="w-full rounded-xl bg-background ring-1 ring-border px-3 py-2 text-sm"
          onKeyDown={(e) => e.key === "Enter" && name.trim() && submit()}
        />
        {error && <p className="text-sm text-danger-fg">{error}</p>}
        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm text-foreground/60 hover:text-foreground/90"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={!name.trim() || submitting}
            className="rounded-xl bg-accent px-4 py-1.5 text-sm text-white hover:bg-accent-hover disabled:opacity-40"
          >
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
