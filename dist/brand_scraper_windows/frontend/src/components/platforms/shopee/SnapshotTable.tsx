"use client";

import { ShopeeProductRecord } from "@/types";

interface SnapshotTableProps {
  products: ShopeeProductRecord[];
}

function formatPrice(currency: string, value: number): string {
  return `${currency} ${value.toFixed(2)}`;
}

function formatSold(n: number): string {
  if (n >= 1_000_000) {
    const v = n / 1_000_000;
    return `${v >= 10 ? v.toFixed(0) : v.toFixed(1)}M sold`;
  }
  if (n >= 1_000) {
    const v = n / 1_000;
    return `${v >= 10 ? v.toFixed(0) : v.toFixed(1)}k sold`;
  }
  return `${n} sold`;
}

export default function SnapshotTable({
  products,
}: SnapshotTableProps) {
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
              <th className="py-3 px-4 font-medium w-16">Image</th>
              <th className="py-3 px-4 font-medium">Name</th>
              <th className="py-3 px-4 font-medium whitespace-nowrap">Price</th>
              <th className="py-3 px-3 font-medium whitespace-nowrap">Discount</th>
              <th className="py-3 px-3 font-medium whitespace-nowrap">Rating</th>
              <th className="py-3 px-3 font-medium whitespace-nowrap">Sold</th>
              <th className="py-3 px-3 font-medium whitespace-nowrap">Status</th>
            </tr>
          </thead>
          <tbody>
            {products.length === 0 && (
              <tr>
                <td
                  colSpan={7}
                  className="py-8 text-center text-sm text-muted-fg"
                >
                  Waiting for products…
                </td>
              </tr>
            )}
            {products.map((p) => {
              const hasMrp =
                p.price !== null && p.mrp !== null && p.mrp > p.price;
              return (
                <tr
                  key={p.item_id}
                  className="border-t border-border hover:bg-muted/30 transition-colors"
                >
                  <td className="py-2.5 px-4">
                    {p.image_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={p.image_url}
                        alt=""
                        className="h-12 w-12 rounded-lg object-cover ring-1 ring-border"
                        loading="lazy"
                      />
                    ) : (
                      <div className="h-12 w-12 rounded-lg bg-muted ring-1 ring-border" />
                    )}
                  </td>
                  <td className="py-2.5 px-4 max-w-xs">
                    <a
                      href={p.product_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="line-clamp-2 text-foreground/80 hover:text-accent transition-colors"
                    >
                      {p.product_name}
                    </a>
                  </td>
                  <td className="py-2.5 px-4 whitespace-nowrap">
                    {p.price === null ? (
                      <span className="text-muted-fg">—</span>
                    ) : (
                      <div className="flex flex-col leading-tight">
                        {hasMrp && (
                          <span className="text-xs text-muted-fg line-through">
                            {formatPrice(p.currency, p.mrp as number)}
                          </span>
                        )}
                        <span className="font-medium text-foreground/90">
                          {formatPrice(p.currency, p.price)}
                        </span>
                      </div>
                    )}
                  </td>
                  <td className="py-2.5 px-3 whitespace-nowrap">
                    {p.discount_pct !== null ? (
                      <span className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent">
                        -{p.discount_pct}%
                      </span>
                    ) : (
                      <span className="text-muted-fg">—</span>
                    )}
                  </td>
                  <td className="py-2.5 px-3 whitespace-nowrap">
                    {p.rating_star !== null ? (
                      <span className="text-foreground/70">
                        ★ {p.rating_star.toFixed(1)}
                      </span>
                    ) : (
                      <span className="text-muted-fg">—</span>
                    )}
                  </td>
                  <td className="py-2.5 px-3 whitespace-nowrap text-foreground/70">
                    {p.historical_sold_count !== null
                      ? formatSold(p.historical_sold_count)
                      : "—"}
                  </td>
                  <td className="py-2.5 px-3 whitespace-nowrap">
                    {p.is_sold_out ? (
                      <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-foreground/50">
                        Sold out
                      </span>
                    ) : (
                      ""
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
