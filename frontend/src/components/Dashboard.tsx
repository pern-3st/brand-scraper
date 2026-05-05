"use client";

import { useEffect, useRef, useState } from "react";
import { listBrands, createBrand, deleteBrand } from "@/lib/api";
import type { BrandSummary } from "@/types";
import NewBrandModal from "./NewBrandModal";
import ConfirmDialog from "./shell/ConfirmDialog";
import { RowMenu, type RowMenuHandle } from "./shell/RowMenu";

export default function Dashboard({
  onOpenBrand,
}: {
  onOpenBrand: (brandId: string) => void;
}) {
  const [brands, setBrands] = useState<BrandSummary[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pendingDelete, setPendingDelete] = useState<BrandSummary | null>(null);

  useEffect(() => {
    listBrands().then((b) => {
      setBrands(b);
      setLoading(false);
    });
  }, []);

  async function handleCreate(name: string) {
    const brand = await createBrand(name);
    setBrands((prev) => [
      ...prev,
      {
        id: brand.id,
        name: brand.name,
        created_at: brand.created_at,
        source_count: 0,
        latest_run: null,
        latest_source_platform: null,
        latest_source_id: null,
      },
    ]);
    onOpenBrand(brand.id);
  }

  async function handleConfirmDelete() {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    setPendingDelete(null);
    try {
      await deleteBrand(id);
      setBrands((prev) => prev.filter((b) => b.id !== id));
    } catch (e) {
      alert(`Failed to delete brand: ${(e as Error).message}`);
    }
  }

  if (loading) return <p className="text-sm text-muted-fg">Loading…</p>;

  if (brands.length === 0) {
    return (
      <div className="text-center py-24 space-y-4">
        <p className="text-foreground/60">No brands yet.</p>
        <button
          onClick={() => setModalOpen(true)}
          className="cursor-pointer rounded-xl bg-accent px-6 py-3 text-sm text-white hover:bg-accent-hover"
        >
          Start tracking a brand
        </button>
        <NewBrandModal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          onCreate={handleCreate}
        />
      </div>
    );
  }

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {brands.map((b) => (
          <BrandTile
            key={b.id}
            brand={b}
            onClick={() => onOpenBrand(b.id)}
            onDelete={() => setPendingDelete(b)}
          />
        ))}
        <button
          onClick={() => setModalOpen(true)}
          className="cursor-pointer rounded-2xl ring-1 ring-dashed ring-border p-6 text-sm text-foreground/40 hover:text-foreground/70 hover:ring-foreground/30 transition-colors flex items-center justify-center min-h-[180px]"
        >
          + New brand
        </button>
      </div>
      <NewBrandModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreate={handleCreate}
      />
      {pendingDelete && (
        <ConfirmDialog
          title="Delete brand?"
          body={
            <>
              This will permanently delete{" "}
              <span className="font-medium">{pendingDelete.name}</span> and all of
              its sources and run history. This cannot be undone.
            </>
          }
          confirmLabel="Delete"
          onCancel={() => setPendingDelete(null)}
          onConfirm={handleConfirmDelete}
        />
      )}
    </>
  );
}

function BrandTile({
  brand,
  onClick,
  onDelete,
}: {
  brand: BrandSummary;
  onClick: () => void;
  onDelete: () => void;
}) {
  const r = brand.latest_run;
  const noSources = brand.source_count === 0;
  const menuRef = useRef<RowMenuHandle>(null);
  return (
    <div className="group relative">
      <button
        onClick={onClick}
        onContextMenu={(e) => {
          e.preventDefault();
          menuRef.current?.openAt(e.clientX, e.clientY);
        }}
        className="w-full h-full min-h-[180px] cursor-pointer rounded-2xl bg-card ring-1 ring-border p-6 text-left hover:ring-accent/40 transition-colors flex flex-col gap-4"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1 min-w-0 flex-1">
            <h2 className="text-lg font-semibold text-foreground truncate">
              {brand.name}
            </h2>
            <div className="text-xs text-muted-fg uppercase tracking-wider truncate">
              {brand.source_count}{" "}
              {brand.source_count === 1 ? "source" : "sources"}
            </div>
          </div>
          <span aria-hidden className="shrink-0 w-6" />
        </div>

        <div className="mt-auto">
          {noSources ? (
            <div className="text-sm text-muted-fg">
              No data yet — open to configure →
            </div>
          ) : !r ? (
            <div className="flex items-center gap-2 text-foreground">
              <StatusDot status={null} />
              <span>Never run</span>
            </div>
          ) : (
            <div className="space-y-1">
              <div className="flex items-center gap-2 text-foreground">
                <StatusDot status={r.status} />
                <span>
                  Updated {relativeTime(r.created_at)} · {statusLabel(r.status)}
                </span>
              </div>
              {r.status === "ok" && r.aggregates.product_count != null && (
                <div className="text-sm text-muted-fg">
                  {r.aggregates.product_count} products
                </div>
              )}
            </div>
          )}
        </div>
      </button>
      <div className="absolute top-3 right-3">
        <RowMenu
          ref={menuRef}
          ariaLabel="Brand actions"
          items={[
            { label: "Delete", destructive: true, onSelect: onDelete },
          ]}
        />
      </div>
    </div>
  );
}

function StatusDot({ status }: { status: string | null }) {
  const cls =
    status === "ok"
      ? "bg-emerald-500"
      : status === "in_progress"
        ? "bg-amber-500 animate-pulse"
        : status === "error"
          ? "bg-red-500"
          : "bg-foreground/20";
  return (
    <span
      aria-hidden
      className={`inline-block h-1.5 w-1.5 rounded-full shrink-0 ${cls}`}
    />
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

function relativeTime(iso: string): string {
  let ms: number;
  const parsed = Date.parse(iso);
  if (!Number.isNaN(parsed)) {
    ms = Date.now() - parsed;
  } else {
    const m = iso.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/);
    if (!m) return iso;
    ms = Date.now() - Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
  }
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}
