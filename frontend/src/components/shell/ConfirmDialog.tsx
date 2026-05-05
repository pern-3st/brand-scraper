"use client";

import type { ReactNode } from "react";

export default function ConfirmDialog({
  title,
  body,
  confirmLabel,
  onCancel,
  onConfirm,
}: {
  title: string;
  body: ReactNode;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
      <div className="rounded-2xl bg-card ring-1 ring-border p-6 max-w-sm space-y-4">
        <h2 className="font-semibold text-foreground">{title}</h2>
        <p className="text-sm text-foreground/70">{body}</p>
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="cursor-pointer rounded-xl px-4 py-2 text-sm text-foreground/70 hover:bg-foreground/5"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="cursor-pointer rounded-xl bg-danger px-4 py-2 text-sm text-white hover:bg-danger-hover"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
