"use client";

import { useEffect, useState } from "react";
import { getSettings, updateSettings } from "@/lib/api";
import type { Settings } from "@/types";

export default function SettingsModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [current, setCurrent] = useState<Settings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setApiKey("");
    getSettings()
      .then((s) => {
        setCurrent(s);
        setModel(s.openrouter_model);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load settings")
      );
  }, [open]);

  if (!open) return null;

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const patch: { openrouter_api_key?: string; openrouter_model?: string } = {};
      if (apiKey.trim()) patch.openrouter_api_key = apiKey.trim();
      if (model.trim() && model.trim() !== current?.openrouter_model) {
        patch.openrouter_model = model.trim();
      }
      if (Object.keys(patch).length === 0) {
        onClose();
        return;
      }
      await updateSettings(patch);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  const keyStatus = current
    ? current.openrouter_api_key_set
      ? `Saved key: ${current.openrouter_api_key_hint}`
      : "No key saved yet"
    : "Loading…";

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
      <div className="bg-card rounded-2xl ring-1 ring-border p-6 w-[min(90vw,480px)] space-y-4">
        <h2 className="text-sm font-semibold text-foreground/80 uppercase tracking-wider">
          Settings
        </h2>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-foreground/70">
            OpenRouter API key
          </label>
          <input
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={current?.openrouter_api_key_set ? "Enter a new key to replace" : "sk-or-..."}
            className="w-full rounded-xl bg-background ring-1 ring-border px-3 py-2 text-sm font-mono"
          />
          <p className="text-xs text-foreground/50">{keyStatus}</p>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-foreground/70">
            Model
          </label>
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="x-ai/grok-4.1-fast"
            className="w-full rounded-xl bg-background ring-1 ring-border px-3 py-2 text-sm font-mono"
          />
        </div>

        {error && <p className="text-sm text-danger-fg">{error}</p>}

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm text-foreground/60 hover:text-foreground/90"
          >
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="rounded-xl bg-accent px-4 py-1.5 text-sm text-white hover:bg-accent-hover disabled:opacity-40"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
