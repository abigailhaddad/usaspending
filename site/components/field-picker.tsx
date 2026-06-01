"use client";

import { useEffect, useState } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";

type Field = { value: string; label: string };

export function FieldPicker({
  dataset, exclude, onPick,
}: { dataset: string; exclude: string[]; onPick: (field: string, label: string) => void }) {
  const [fields, setFields] = useState<Field[]>([]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    fetch(`/api/fields?dataset=${dataset}`).then((r) => r.json()).then((j) => setFields(j.fields || [])).catch(() => setFields([]));
  }, [dataset]);

  const shown = fields
    .filter((f) => !exclude.includes(f.value) && f.label.toLowerCase().includes(q.toLowerCase()))
    .slice(0, 300);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger className="inline-flex h-9 items-center rounded-lg border border-dashed px-3 text-sm transition-colors hover:bg-muted">
        + Add filter
      </PopoverTrigger>
      <PopoverContent className="w-80 p-2" align="start">
        <Input className="mb-2 h-8" placeholder={`Search ${fields.length || "all"} fields…`}
          value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
        <div className="max-h-72 overflow-y-auto">
          {shown.map((f) => (
            <button key={f.value}
              className="block w-full truncate rounded px-2 py-1 text-left text-sm hover:bg-muted"
              onClick={() => { onPick(f.value, f.label); setOpen(false); setQ(""); }}>
              {f.label}
            </button>
          ))}
          {shown.length === 0 && <p className="px-2 text-xs text-muted-foreground">no matching field</p>}
        </div>
      </PopoverContent>
    </Popover>
  );
}
