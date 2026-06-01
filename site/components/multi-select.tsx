"use client";

import { useEffect, useState } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";

type Opt = { value: string; label: string };

export function MultiSelect({
  field, dataset, label, value, onChange,
}: {
  field: string; dataset: string; label: string;
  value: string[]; onChange: (v: string[]) => void;
}) {
  const [opts, setOpts] = useState<Opt[] | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    setOpts(null);
    fetch(`/api/filter_options?field=${field}&dataset=${dataset}`)
      .then((r) => r.json())
      .then((j) => setOpts(j.options ?? []))
      .catch(() => setOpts([]));
  }, [field, dataset]);

  const shown = (opts ?? []).filter((o) => o.label.toLowerCase().includes(q.toLowerCase()));
  const toggle = (v: string) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);

  return (
    <Popover>
      <PopoverTrigger className="inline-flex h-9 items-center gap-1.5 rounded-lg border bg-background px-3 text-sm shadow-xs transition-colors hover:bg-muted">
        {label}{value.length > 0 && <span className="rounded bg-primary px-1.5 text-xs text-primary-foreground">{value.length}</span>}
      </PopoverTrigger>
      <PopoverContent className="w-72 p-2" align="start">
        <Input className="mb-2 h-8" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
        {value.length > 0 && (
          <button className="mb-1 text-xs text-muted-foreground underline" onClick={() => onChange([])}>clear {value.length}</button>
        )}
        <div className="max-h-64 space-y-1 overflow-y-auto">
          {opts === null && <p className="text-xs text-muted-foreground">loading…</p>}
          {opts !== null && shown.length === 0 && <p className="text-xs text-muted-foreground">no options</p>}
          {shown.map((o) => (
            <label key={o.value} className="flex cursor-pointer items-center gap-2 text-sm">
              <Checkbox checked={value.includes(o.value)} onCheckedChange={() => toggle(o.value)} />
              {o.label}
            </label>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
