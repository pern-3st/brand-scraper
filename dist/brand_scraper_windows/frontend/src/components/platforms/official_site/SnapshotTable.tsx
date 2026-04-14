"use client";

import { CategoryResult } from "@/types";

interface SnapshotTableProps {
  brand: string;
  section: string;
  results: CategoryResult[];
}

export default function SnapshotTable({
  brand,
  section,
  results,
}: SnapshotTableProps) {
  return (
    <div className="rounded-2xl bg-card shadow-md shadow-accent/5 ring-1 ring-border overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-border">
        <h2 className="text-lg font-semibold">
          {brand}{" "}
          <span className="text-foreground/40 font-normal">
            — {section.charAt(0).toUpperCase() + section.slice(1)}
          </span>
        </h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-muted/50 text-left text-foreground/60">
              <th className="py-3 px-6 font-medium">Category</th>
              <th className="py-3 px-4 font-medium">Status</th>
              <th className="py-3 px-4 font-medium">Lowest</th>
              <th className="py-3 px-4 font-medium">Highest</th>
              <th className="py-3 px-4 font-medium">Scanned</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr
                key={r.category}
                className="border-t border-border hover:bg-muted/30 transition-colors"
              >
                <td className="py-3 px-6 font-medium">{r.category}</td>
                <td className="py-3 px-4">
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      r.status === "found"
                        ? "bg-emerald-100 text-emerald-700"
                        : "bg-pink-100 text-pink-600"
                    }`}
                  >
                    {r.status === "found" ? "Found" : "Not found"}
                  </span>
                </td>
                <td className="py-3 px-4">
                  {r.lowest_price !== null ? r.lowest_price.toFixed(2) : "—"}
                </td>
                <td className="py-3 px-4">
                  {r.highest_price !== null ? r.highest_price.toFixed(2) : "—"}
                </td>
                <td className="py-3 px-4">{r.products_scanned}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
