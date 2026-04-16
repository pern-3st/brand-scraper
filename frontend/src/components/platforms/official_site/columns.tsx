import type { Column } from "@/components/SnapshotTable";

function formatPrice(currency: string, v: number): string {
  return currency ? `${currency} ${v.toFixed(2)}` : v.toFixed(2);
}

export const officialSiteColumns: Column[] = [
  {
    key: "category",
    label: "Category",
    className: "px-4 whitespace-nowrap text-foreground/70",
    render: (p) => p.category ?? "—",
  },
  {
    key: "name",
    label: "Name",
    className: "px-4 max-w-xs",
    render: (p) =>
      p.product_url ? (
        <a
          href={p.product_url}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-2 text-foreground/80 hover:text-accent transition-colors"
        >
          {p.product_name}
        </a>
      ) : (
        <span className="line-clamp-2 text-foreground/80">{p.product_name}</span>
      ),
  },
  {
    key: "price",
    label: "Price",
    className: "px-4 whitespace-nowrap",
    render: (p) =>
      p.price === null ? (
        <span className="text-muted-fg">—</span>
      ) : (
        <div className="flex flex-col leading-tight">
          {p.mrp !== null && p.mrp > p.price && (
            <span className="text-xs text-muted-fg line-through">
              {formatPrice(p.currency, p.mrp)}
            </span>
          )}
          <span className="font-medium text-foreground/90">
            {formatPrice(p.currency, p.price)}
          </span>
        </div>
      ),
  },
  {
    key: "discount",
    label: "Discount",
    className: "px-4 whitespace-nowrap",
    render: (p) =>
      p.discount_pct !== null ? (
        <span className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent">
          -{p.discount_pct}%
        </span>
      ) : (
        <span className="text-muted-fg">—</span>
      ),
  },
];
