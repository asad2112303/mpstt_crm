"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "@/lib/api";
import { Input } from "@/components/ui/input";

interface Hit {
  kind: string;
  id: string;
  label: string;
  href: string;
}

export function GlobalSearch() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  const { data } = useQuery({
    queryKey: ["global-search", q],
    queryFn: async () => (await api<Hit[]>("/api/v1/search", { searchParams: { q } })).data,
    enabled: q.length >= 2,
  });

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  return (
    <div ref={boxRef} className="relative hidden w-72 md:block">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
      <Input
        className="pl-8"
        placeholder="Search everything…"
        aria-label="Global search"
        value={q}
        onFocus={() => setOpen(true)}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }}
      />
      {open && q.length >= 2 && data && (
        <ul className="absolute z-40 mt-1 max-h-80 w-full overflow-auto rounded-md border border-border bg-popover py-1 shadow-lg">
          {data.length === 0 && (
            <li className="px-3 py-2 text-sm text-muted-foreground">No matches</li>
          )}
          {data.map((hit) => (
            <li key={`${hit.kind}-${hit.id}`}>
              <Link
                href={hit.href}
                onClick={() => { setOpen(false); setQ(""); }}
                className="flex items-center justify-between px-3 py-1.5 text-sm hover:bg-muted"
              >
                <span className="truncate">{hit.label}</span>
                <span className="ml-2 shrink-0 rounded bg-secondary px-1.5 py-0.5 text-[10px] uppercase text-secondary-foreground">
                  {hit.kind}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
