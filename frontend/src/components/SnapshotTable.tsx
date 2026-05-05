"use client";

import { Fragment, useMemo, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  type ColumnDef,
  type SortingState,
  type ColumnFiltersState,
} from "@tanstack/react-table";
import type { FieldType, UnifiedColumn } from "@/types";
import FilterChips, { filterFns } from "./snapshot/FilterChips";

export type TableRow = Record<string, unknown>;
export type Renderer = (value: unknown, row: TableRow) => React.ReactNode;

interface Props {
  rows: TableRow[];
  columns: UnifiedColumn[];
  emptyMessage?: string;
  title?: string;
  rightLabel?: string;
  interactive?: boolean;
}

// Columns that exist on ProductRecord but are folded into other cells
// (price → price+mrp+currency, product_name → linked to product_url).
const HIDDEN_IDS = new Set([
  "scraped_at",
  "currency",
  "mrp",
  "product_url",
  "product_key",
  "monthly_sold_text",
  "category",
]);

const LABEL_OVERRIDES: Record<string, string> = {
  product_name: "Name",
  image_url: "Image",
  price: "Price",
  discount_pct: "Discount",
  is_sold_out: "Sold out",
  item_id: "Item ID",
  rating_star: "Rating",
  historical_sold_count: "Sold (total)",
  monthly_sold_count: "Sold (monthly)",
};

export default function SnapshotTable({
  rows,
  columns,
  emptyMessage = "No products.",
  title = "Products",
  rightLabel,
  interactive = false,
}: Props) {
  const visible = useMemo(
    () => columns.filter((c) => !HIDDEN_IDS.has(c.id)),
    [columns],
  );

  const tanstackColumns = useMemo<ColumnDef<TableRow>[]>(
    () =>
      visible.map((c) => ({
        id: c.id,
        accessorFn: (row) => row[c.id],
        header: labelFor(c),
        enableSorting: true,
        sortingFn: c.type === "int" || c.type === "float" ? "basic" : "alphanumeric",
        filterFn: filterFns[c.id],
        cell: ({ row }) => <Cell col={c} row={row.original} />,
        meta: { col: c },
      })),
    [visible],
  );

  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);

  const table = useReactTable({
    data: rows,
    columns: tanstackColumns,
    state: { sorting, globalFilter, columnFilters },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onColumnFiltersChange: setColumnFilters,
    globalFilterFn: (row, _columnId, value) => {
      if (!value) return true;
      const name = row.original.product_name;
      return typeof name === "string"
        ? name.toLowerCase().includes(String(value).toLowerCase())
        : false;
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const renderRows = interactive
    ? table.getRowModel().rows.map((r) => r.original)
    : rows;

  return (
    <div className="rounded-2xl bg-card shadow-md shadow-accent/5 ring-1 ring-border overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-border">
        <h2 className="text-sm font-semibold text-foreground/50 uppercase tracking-wider">
          {title}
        </h2>
        <span className="text-xs text-muted-fg">
          {rightLabel ?? itemsLabel(interactive, table.getFilteredRowModel().rows.length, rows.length)}
        </span>
      </div>
      {interactive && (
        <div className="flex flex-wrap items-center gap-2 px-6 py-3 border-b border-border bg-card">
          <div className="relative flex-1 min-w-[12rem] max-w-sm">
            <input
              type="text"
              value={globalFilter}
              onChange={(e) => setGlobalFilter(e.target.value)}
              placeholder="Search name…"
              aria-label="Search by name"
              className="w-full rounded-lg bg-muted/60 ring-1 ring-border px-3 py-1.5 pr-7 text-xs text-foreground/90 placeholder:text-foreground/40 focus:outline-none focus:ring-accent/40"
            />
            {globalFilter && (
              <button
                type="button"
                onClick={() => setGlobalFilter("")}
                aria-label="Clear search"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-foreground/40 hover:text-foreground/70"
              >
                ×
              </button>
            )}
          </div>
          <FilterChips
            columns={visible}
            filters={columnFilters}
            setFilters={(updater) => setColumnFilters(updater)}
          />
        </div>
      )}
      <div className="max-h-[640px] overflow-x-auto overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur text-left text-foreground/60">
            <tr>
              {interactive
                ? table.getHeaderGroups()[0].headers.map((h) => {
                    const c = (h.column.columnDef.meta as { col: UnifiedColumn }).col;
                    const sort = h.column.getIsSorted();
                    return (
                      <th
                        key={h.id}
                        onClick={h.column.getToggleSortingHandler()}
                        className={`py-3 px-4 font-medium whitespace-nowrap cursor-pointer select-none hover:text-foreground/80 ${
                          c.source === "enrichment" ? "bg-accent-soft/40" : ""
                        }`}
                        title={
                          c.source === "enrichment"
                            ? `Enrichment · ${c.enrichment_id ?? ""}`
                            : undefined
                        }
                      >
                        <span className="inline-flex items-center gap-1">
                          {labelFor(c)}
                          <SortGlyph state={sort} />
                        </span>
                      </th>
                    );
                  })
                : visible.map((c) => (
                    <th
                      key={c.id}
                      className={`py-3 px-4 font-medium whitespace-nowrap ${
                        c.source === "enrichment" ? "bg-accent-soft/40" : ""
                      }`}
                      title={
                        c.source === "enrichment"
                          ? `Enrichment · ${c.enrichment_id ?? ""}`
                          : undefined
                      }
                    >
                      {labelFor(c)}
                    </th>
                  ))}
            </tr>
          </thead>
          <tbody>
            {renderRows.length === 0 && (
              <tr>
                <td
                  colSpan={Math.max(1, visible.length)}
                  className="py-8 text-center text-sm text-muted-fg"
                >
                  {emptyMessage}
                </td>
              </tr>
            )}
            {renderRows.map((row, idx) => (
              <tr
                key={rowKey(row, idx)}
                className="border-t border-border hover:bg-muted/30 transition-colors"
              >
                {visible.map((c) => (
                  <td key={c.id} className="py-2.5 px-4 align-top">
                    <Cell col={c} row={row} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function labelFor(c: UnifiedColumn): string {
  if (c.source === "scrape") return LABEL_OVERRIDES[c.id] ?? c.label;
  return c.label;
}

function rowKey(row: TableRow, idx: number): string {
  const pk = row.product_key;
  if (typeof pk === "string" || typeof pk === "number") return `${pk}`;
  const id = row.item_id;
  if (typeof id === "number" || typeof id === "string") return `${id}:${idx}`;
  return `${idx}`;
}

function Cell({ col, row }: { col: UnifiedColumn; row: TableRow }) {
  const value = row[col.id];
  const override = overridesById[col.id];
  if (override) return <Fragment>{override(value, row)}</Fragment>;
  const byType = col.type ? rendererByType[col.type] : null;
  if (byType) return <Fragment>{byType(value, row)}</Fragment>;
  return <Fragment>{fallbackRenderer(value)}</Fragment>;
}

// -- default renderers by type ---------------------------------------------

const Dash = () => <span className="text-muted-fg">—</span>;

export const rendererByType: Record<FieldType, Renderer> = {
  str: (v) => {
    if (v == null || v === "") return <Dash />;
    return <span className="whitespace-pre-wrap break-words line-clamp-4">{String(v)}</span>;
  },
  int: (v) => {
    if (v == null) return <Dash />;
    const n = Number(v);
    if (!Number.isFinite(n)) return <Dash />;
    return <span className="tabular-nums text-foreground/80">{n.toLocaleString()}</span>;
  },
  float: (v) => {
    if (v == null) return <Dash />;
    const n = Number(v);
    if (!Number.isFinite(n)) return <Dash />;
    return <span className="tabular-nums text-foreground/80">{n.toFixed(2)}</span>;
  },
  bool: (v) => {
    if (v === true) {
      return (
        <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
          Yes
        </span>
      );
    }
    if (v === false) {
      return <span className="text-muted-fg">No</span>;
    }
    return <Dash />;
  },
  "list[str]": (v) => {
    if (!Array.isArray(v) || v.length === 0) return <Dash />;
    return (
      <div className="flex flex-wrap gap-1">
        {v.map((item, i) => (
          <span
            key={i}
            className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs text-foreground/70"
          >
            {String(item)}
          </span>
        ))}
      </div>
    );
  },
};

function fallbackRenderer(v: unknown): React.ReactNode {
  if (v == null || v === "") return <Dash />;
  if (Array.isArray(v)) return rendererByType["list[str]"](v, {});
  if (typeof v === "boolean") return rendererByType.bool(v, {});
  if (typeof v === "number") return rendererByType.float(v, {});
  if (typeof v === "object") {
    return (
      <span className="font-mono text-xs text-muted-fg">
        {JSON.stringify(v)}
      </span>
    );
  }
  return <span className="whitespace-pre-wrap break-words line-clamp-4">{String(v)}</span>;
}

// -- id-specific overrides (ProductRecord visuals) -------------------------

function formatPrice(currency: string, v: number): string {
  return currency ? `${currency} ${v.toFixed(2)}` : v.toFixed(2);
}

export const overridesById: Record<string, Renderer> = {
  image_url: (v) =>
    typeof v === "string" && v ? (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={v}
        alt=""
        className="h-12 w-12 rounded-lg object-cover ring-1 ring-border"
        loading="lazy"
      />
    ) : (
      <div className="h-12 w-12 rounded-lg bg-muted ring-1 ring-border" />
    ),
  product_name: (v, row) => {
    const name = typeof v === "string" ? v : String(v ?? "");
    const url = typeof row.product_url === "string" ? row.product_url : null;
    if (url) {
      return (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-2 text-foreground/80 hover:text-accent transition-colors max-w-xs inline-block"
        >
          {name}
        </a>
      );
    }
    return <span className="line-clamp-2 text-foreground/80 max-w-xs inline-block">{name}</span>;
  },
  price: (v, row) => {
    if (v == null) return <Dash />;
    const price = Number(v);
    const mrp = typeof row.mrp === "number" ? row.mrp : null;
    const currency = typeof row.currency === "string" ? row.currency : "";
    return (
      <div className="flex flex-col leading-tight whitespace-nowrap">
        {mrp !== null && mrp > price && (
          <span className="text-xs text-muted-fg line-through">
            {formatPrice(currency, mrp)}
          </span>
        )}
        <span className="font-medium text-foreground/90">
          {formatPrice(currency, price)}
        </span>
      </div>
    );
  },
  discount_pct: (v) => {
    if (v == null) return <Dash />;
    return (
      <span className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent">
        -{Number(v)}%
      </span>
    );
  },
  rating_star: (v) => {
    if (v == null) return <Dash />;
    return <span className="text-foreground/70 whitespace-nowrap">★ {Number(v).toFixed(1)}</span>;
  },
  is_sold_out: (v) =>
    v ? (
      <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-foreground/50">
        Sold out
      </span>
    ) : (
      <span />
    ),
  voucher_discount: (v, row) => {
    if (v == null) return <Dash />;
    const n = Number(v);
    if (!Number.isFinite(n)) return <Dash />;
    // Shopee 1e5 micro-units → currency.
    const amount = n / 100_000;
    const currency = typeof row.currency === "string" ? row.currency : "";
    return (
      <span className="tabular-nums whitespace-nowrap text-foreground/80">
        {currency ? `${currency} ${amount.toFixed(2)}` : amount.toFixed(2)}
      </span>
    );
  },
  item_id: (v) => (v == null ? <Dash /> : <span className="font-mono text-xs text-muted-fg">{String(v)}</span>),
};

// -- helpers ----------------------------------------------------------------

/** Build UnifiedColumn descriptors for ProductRecord-shaped rows (used by
 *  progress views that stream records before a completed run exists). */
export function productRecordColumns(platform: "shopee" | "official_site"): UnifiedColumn[] {
  const base: UnifiedColumn[] = [
    { id: "image_url", label: "image_url", type: "str", source: "scrape", enrichment_id: null },
    { id: "product_name", label: "product_name", type: "str", source: "scrape", enrichment_id: null },
    { id: "price", label: "price", type: "float", source: "scrape", enrichment_id: null },
    { id: "discount_pct", label: "discount_pct", type: "int", source: "scrape", enrichment_id: null },
    ...(platform === "shopee"
      ? ([
          { id: "rating_star", label: "rating_star", type: "float", source: "scrape", enrichment_id: null },
          { id: "historical_sold_count", label: "historical_sold_count", type: "int", source: "scrape", enrichment_id: null },
          { id: "monthly_sold_count", label: "monthly_sold_count", type: "int", source: "scrape", enrichment_id: null },
        ] as UnifiedColumn[])
      : []),
    { id: "is_sold_out", label: "is_sold_out", type: "bool", source: "scrape", enrichment_id: null },
  ];
  return base;
}

function itemsLabel(interactive: boolean, filtered: number, total: number): string {
  if (!interactive || filtered === total) return `${total} items`;
  return `${filtered} of ${total} items`;
}

function SortGlyph({ state }: { state: false | "asc" | "desc" }) {
  if (state === "asc") return <span className="text-foreground/70">▲</span>;
  if (state === "desc") return <span className="text-foreground/70">▼</span>;
  return <span className="text-foreground/20">↕</span>;
}
