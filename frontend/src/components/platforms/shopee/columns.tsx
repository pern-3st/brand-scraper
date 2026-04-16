import type { Column } from "@/components/SnapshotTable";

function formatPrice(currency: string, v: number): string {
  return `${currency} ${v.toFixed(2)}`;
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

export const shopeeColumns: Column[] = [
  {
    key: "image",
    label: "Image",
    className: "px-4",
    headClassName: "px-4 w-16",
    render: (p) =>
      p.image_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={p.image_url}
          alt=""
          className="h-12 w-12 rounded-lg object-cover ring-1 ring-border"
          loading="lazy"
        />
      ) : (
        <div className="h-12 w-12 rounded-lg bg-muted ring-1 ring-border" />
      ),
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
    className: "px-3 whitespace-nowrap",
    headClassName: "px-3",
    render: (p) =>
      p.discount_pct !== null ? (
        <span className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent">
          -{p.discount_pct}%
        </span>
      ) : (
        <span className="text-muted-fg">—</span>
      ),
  },
  {
    key: "rating",
    label: "Rating",
    className: "px-3 whitespace-nowrap",
    headClassName: "px-3",
    render: (p) =>
      p.rating_star !== null ? (
        <span className="text-foreground/70">★ {p.rating_star.toFixed(1)}</span>
      ) : (
        <span className="text-muted-fg">—</span>
      ),
  },
  {
    key: "sold",
    label: "Sold",
    className: "px-3 whitespace-nowrap text-foreground/70",
    headClassName: "px-3",
    render: (p) =>
      p.historical_sold_count !== null
        ? formatSold(p.historical_sold_count)
        : "—",
  },
  {
    key: "stock",
    label: "Status",
    className: "px-3 whitespace-nowrap",
    headClassName: "px-3",
    render: (p) =>
      p.is_sold_out ? (
        <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-foreground/50">
          Sold out
        </span>
      ) : (
        ""
      ),
  },
];
