"use client";

import { useEffect, useRef, useState } from "react";
import { listBrands, createBrand, deleteBrand } from "@/lib/api";
import type { BrandSummary } from "@/types";
import NewBrandModal from "./NewBrandModal";
import { formatPlatform } from "@/lib/format";

export default function Dashboard({
  onOpenBrand,
}: {
  onOpenBrand: (brandId: string) => void;
}) {
  const [brands, setBrands] = useState<BrandSummary[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [menu, setMenu] = useState<{
    brandId: string;
    x: number;
    y: number;
  } | null>(null);
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
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {brands.map((b) => (
          <BrandTile
            key={b.id}
            brand={b}
            onClick={() => onOpenBrand(b.id)}
            onContextMenu={(e) => {
              e.preventDefault();
              setMenu({ brandId: b.id, x: e.clientX, y: e.clientY });
            }}
            onDelete={() => setPendingDelete(b)}
          />
        ))}
        <button
          onClick={() => setModalOpen(true)}
          className="cursor-pointer min-h-56 rounded-3xl ring-1 ring-dashed ring-border p-10 text-lg text-foreground/40 hover:text-foreground/70 hover:ring-foreground/30 transition-colors"
        >
          + New brand
        </button>
      </div>
      <NewBrandModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreate={handleCreate}
      />
      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          onClose={() => setMenu(null)}
          onDelete={() => {
            const brand = brands.find((b) => b.id === menu.brandId);
            setMenu(null);
            if (brand) setPendingDelete(brand);
          }}
        />
      )}
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
  onContextMenu,
  onDelete,
}: {
  brand: BrandSummary;
  onClick: () => void;
  onContextMenu: (e: React.MouseEvent) => void;
  onDelete: () => void;
}) {
  const r = brand.latest_run;
  const noData = !r || brand.source_count === 0;
  return (
    <button
      onClick={onClick}
      onContextMenu={onContextMenu}
      className="group relative cursor-pointer rounded-3xl bg-card ring-1 ring-border p-10 text-left hover:ring-accent/40 transition-colors space-y-6 min-h-56"
    >
      <span
        role="button"
        tabIndex={0}
        onClick={(ev) => {
          ev.stopPropagation();
          onDelete();
        }}
        onKeyDown={(ev) => {
          if (ev.key === "Enter" || ev.key === " ") {
            ev.stopPropagation();
            ev.preventDefault();
            onDelete();
          }
        }}
        className="absolute top-4 right-5 text-2xl leading-none text-foreground/30 hover:text-danger-fg opacity-0 group-hover:opacity-100 transition-opacity px-2 py-1 cursor-pointer"
        aria-label="Delete brand"
        title="Delete brand"
      >
        ×
      </span>
      <div className="text-2xl font-semibold text-foreground">{brand.name}</div>
      {noData ? (
        <p className="text-base text-muted-fg">
          No data yet — open to configure →
        </p>
      ) : (
        <>
          <div className="text-sm text-muted-fg">
            {formatPlatform(brand.latest_source_platform)}
            {brand.source_count > 1 && (
              <span className="ml-1 text-foreground/40">
                +{brand.source_count - 1} more
              </span>
            )}
          </div>
          <div className="text-base text-muted-fg">
            {r!.aggregates.product_count} products · updated{" "}
            {relativeTime(r!.created_at)}
          </div>
        </>
      )}
    </button>
  );
}

function ContextMenu({
  x,
  y,
  onClose,
  onDelete,
}: {
  x: number;
  y: number;
  onClose: () => void;
  onDelete: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", handle);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handle);
      document.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      style={{ left: x, top: y }}
      className="fixed z-50 min-w-36 rounded-xl bg-card ring-1 ring-border shadow-lg py-1"
    >
      <button
        onClick={onDelete}
        className="cursor-pointer w-full text-left px-3 py-2 text-sm text-danger-fg hover:bg-danger/10"
      >
        Delete
      </button>
    </div>
  );
}

function ConfirmDialog({
  title,
  body,
  confirmLabel,
  onCancel,
  onConfirm,
}: {
  title: string;
  body: React.ReactNode;
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
