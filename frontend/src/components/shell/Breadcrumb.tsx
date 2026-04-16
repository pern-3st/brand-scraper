"use client";

export interface Crumb {
  label: string;
  onClick?: () => void;
}

export default function Breadcrumb({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav className="flex items-center gap-3 text-xl">
      {crumbs.map((c, i) => {
        const isLast = i === crumbs.length - 1;
        const clickable = !!c.onClick && !isLast;
        return (
          <span key={i} className="flex items-center gap-2">
            {i > 0 && <span className="text-foreground/25">/</span>}
            {clickable ? (
              <button
                onClick={c.onClick}
                className="text-foreground/40 hover:text-foreground/70 transition-colors"
              >
                {c.label}
              </button>
            ) : (
              <span
                className={
                  isLast
                    ? "font-medium text-foreground/80"
                    : "text-foreground/40"
                }
              >
                {c.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
