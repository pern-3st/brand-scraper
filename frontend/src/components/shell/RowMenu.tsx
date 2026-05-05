"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";

export type RowMenuItem = {
  label: string;
  onSelect: () => void;
  destructive?: boolean;
};

export interface RowMenuHandle {
  openAt: (x: number, y: number) => void;
}

type OpenState = { x: number; y: number } | null;
const MENU_MIN_WIDTH = 144; // matches min-w-36

interface Props {
  items: RowMenuItem[];
  ariaLabel?: string;
  parentGroup?: "card";
}

export const RowMenu = forwardRef<RowMenuHandle, Props>(function RowMenu(
  { items, ariaLabel = "More actions", parentGroup },
  ref,
) {
  const [open, setOpen] = useState<OpenState>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useImperativeHandle(ref, () => ({
    openAt: (x, y) => setOpen({ x, y }),
  }));

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (
        menuRef.current?.contains(e.target as Node) ||
        buttonRef.current?.contains(e.target as Node)
      ) {
        return;
      }
      setOpen(null);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(null);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const isOpen = open !== null;
  const hoverReveal =
    parentGroup === "card"
      ? "opacity-0 group-hover/card:opacity-100 focus:opacity-100 data-[open]:opacity-100"
      : "opacity-0 group-hover:opacity-100 focus:opacity-100 data-[open]:opacity-100";

  return (
    <div className="relative inline-block">
      <button
        ref={buttonRef}
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((s) => {
            if (s) return null;
            const r = buttonRef.current?.getBoundingClientRect();
            if (!r) return null;
            return { x: r.right - MENU_MIN_WIDTH, y: r.bottom + 4 };
          });
        }}
        data-open={isOpen ? "" : undefined}
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        className={`cursor-pointer rounded-md p-2 text-foreground/40 hover:text-foreground/80 hover:bg-foreground/5 transition-colors ${hoverReveal}`}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="currentColor"
          aria-hidden
        >
          <circle cx="3" cy="8" r="1.5" />
          <circle cx="8" cy="8" r="1.5" />
          <circle cx="13" cy="8" r="1.5" />
        </svg>
      </button>
      {open && (
        <div
          ref={menuRef}
          role="menu"
          style={{ position: "fixed", left: open.x, top: open.y }}
          className="z-50 min-w-36 rounded-xl bg-card ring-1 ring-border shadow-lg py-1"
        >
          {items.map((item) => (
            <button
              key={item.label}
              role="menuitem"
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setOpen(null);
                item.onSelect();
              }}
              className={
                item.destructive
                  ? "cursor-pointer w-full text-left px-3 py-2 text-sm text-danger-fg hover:bg-danger/10"
                  : "cursor-pointer w-full text-left px-3 py-2 text-sm text-foreground/80 hover:bg-foreground/5"
              }
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
});
