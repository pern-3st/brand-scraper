"use client";

import { ProductRecord } from "@/types";

export interface Column {
  key: string;
  label: string;
  render: (r: ProductRecord) => React.ReactNode;
  className?: string;
  headClassName?: string;
}

interface Props {
  products: ProductRecord[];
  columns: Column[];
  emptyMessage?: string;
}

export default function SnapshotTable({
  products,
  columns,
  emptyMessage = "No products.",
}: Props) {
  return (
    <div className="rounded-2xl bg-card shadow-md shadow-accent/5 ring-1 ring-border overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-border">
        <h2 className="text-sm font-semibold text-foreground/50 uppercase tracking-wider">
          Products
        </h2>
        <span className="text-xs text-muted-fg">{products.length} items</span>
      </div>
      <div className="max-h-[640px] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur text-left text-foreground/60">
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  className={`py-3 font-medium whitespace-nowrap ${c.headClassName ?? "px-4"}`}
                >
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {products.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length}
                  className="py-8 text-center text-sm text-muted-fg"
                >
                  {emptyMessage}
                </td>
              </tr>
            )}
            {products.map((p, idx) => (
              <tr
                key={`${p.item_id ?? p.category ?? "row"}-${p.product_name}-${idx}`}
                className="border-t border-border hover:bg-muted/30 transition-colors"
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={`py-2.5 ${c.className ?? "px-4"}`}
                  >
                    {c.render(p)}
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
