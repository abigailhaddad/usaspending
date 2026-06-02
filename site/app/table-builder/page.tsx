"use client";

import { useEffect, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import type { DateRange } from "react-day-picker";
import { DateRangePicker } from "@/components/date-range";
import { DIMENSIONS, METRICS, FILTER_FIELDS, DATASETS, DATE_FIELDS } from "@/lib/registry";
import { fmtCell } from "@/lib/format";

type Repro = { python: string; sql: string };
type TableResult = {
  label: string; dimension: string; group_cols: number; columns: string[];
  data: (string | number | null)[][]; reproduce: Repro;
};
type Filter = {
  id: number; field: string;
  options: { value: string; label: string }[] | null;
  searchable: boolean; selected: string[]; text: string;
};

const isoLocal = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parseLocal = (s: string) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
let fid = 1;

function Step({ n, title, hint, children }: { n: number; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2.5 text-base">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">{n}</span>
          {title}
        </CardTitle>
        {hint && <p className="pl-8 text-sm text-muted-foreground">{hint}</p>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export default function TableBuilder() {
  const [dataset, setDataset] = useState("contracts");
  const [rows, setRows] = useState<string[]>(["funding_subagency"]);
  const [metrics, setMetrics] = useState<string[]>(["obligations"]);
  const [aRange, setARange] = useState<DateRange | undefined>();
  const [dateField, setDateField] = useState("action_date");
  const [filters, setFilters] = useState<Filter[]>([]);
  const [tables, setTables] = useState<TableResult[]>([]);
  const [repro, setRepro] = useState<Repro | null>(null);
  const [status, setStatus] = useState("");
  const loaded = useRef(false);

  function buildParams(): URLSearchParams {
    const p = new URLSearchParams();
    p.set("dataset", dataset);
    if (rows.length) p.set("rows", rows.join(","));
    if (metrics.length) p.set("metric", metrics.join(","));
    if (aRange?.from && aRange?.to) p.set("periodA", `${isoLocal(aRange.from)}..${isoLocal(aRange.to)}`);
    if (dateField !== "action_date") p.set("date_field", dateField);
    for (const f of filters) {
      const vals = f.searchable ? f.text.split(",").map((x) => x.trim()).filter(Boolean) : f.selected;
      if (vals.length) p.set(`filter_${f.field}`, vals.join("|"));
    }
    return p;
  }

  async function run(explicit?: URLSearchParams) {
    setStatus("Running…");
    const p = explicit ?? buildParams();
    if (!explicit) window.history.replaceState(null, "", "?" + p.toString());
    try {
      const j = await (await fetch("/api/table?" + p.toString())).json();
      if (j.error) { setStatus("Error: " + j.error); return; }
      setTables(j.tables);
      if (j.tables.length) setRepro(j.tables[0].reproduce);
      setStatus(`${j.tables.length} table${j.tables.length === 1 ? "" : "s"}`);
    } catch (e) { setStatus("Error: " + (e as Error).message); }
  }

  async function loadOptions(field: string): Promise<Partial<Filter>> {
    try {
      const j = await (await fetch(`/api/filter_options?field=${encodeURIComponent(field)}&dataset=${dataset}`)).json();
      return j.options ? { options: j.options, searchable: false } : { options: [], searchable: true };
    } catch { return { options: [], searchable: true }; }
  }
  async function addFilter(field = "funding_subagency_code", preset: string[] = []) {
    const id = fid++;
    setFilters((fs) => [...fs, { id, field, options: null, searchable: false, selected: preset, text: preset.join(", ") }]);
    const opt = await loadOptions(field);
    setFilters((fs) => fs.map((f) => (f.id === id ? { ...f, ...opt } : f)));
  }
  function updateFilter(id: number, patch: Partial<Filter>) {
    setFilters((fs) => fs.map((f) => (f.id === id ? { ...f, ...patch } : f)));
  }
  async function changeFilterField(id: number, field: string) {
    updateFilter(id, { field, options: null, selected: [], text: "" });
    const opt = await loadOptions(field);
    updateFilter(id, { field, ...opt });
  }

  useEffect(() => {
    if (loaded.current) return; loaded.current = true;
    const p = new URLSearchParams(window.location.search);
    if (![...p.keys()].length) { addFilter(); return; }
    setDataset(p.get("dataset") || "contracts");
    setRows((p.get("rows") || "funding_subagency").split(","));
    setMetrics((p.get("metric") || "obligations").split(","));
    const pa = p.get("periodA"); if (pa) { const [s, e] = pa.split(".."); setARange({ from: parseLocal(s), to: parseLocal(e) }); }
    setDateField(p.get("date_field") || "action_date");
    const fkeys = [...p.keys()].filter((k) => k.startsWith("filter_"));
    fkeys.forEach((k) => addFilter(k.slice(7), (p.get(k) || "").split("|")));
    if (!fkeys.length) addFilter();
    run(p);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = (arr: string[], v: string, set: (a: string[]) => void) =>
    set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  function downloadCSV(columns: string[], data: (string | number | null)[][], name: string) {
    const esc = (x: unknown) => (x == null ? "" : `"${String(x).replace(/"/g, '""')}"`);
    const csv = [columns.map(esc).join(","), ...data.map((r) => r.map(esc).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = name; a.click();
  }
  async function records() {
    setStatus("Fetching matching records…");
    try {
      const j = await (await fetch("/api/detail?" + buildParams().toString())).json();
      if (j.error) { setStatus("Error: " + j.error); return; }
      downloadCSV(j.columns, j.data, "records.csv");
      setStatus(`${j.count} records${j.truncated ? " (capped at 100k)" : ""}`);
    } catch (e) { setStatus("Error: " + (e as Error).message); }
  }
  async function openColab() {
    if (!repro) return;
    setStatus("Creating Colab notebook…");
    try {
      const j = await (await fetch("/api/colab", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sql: repro.sql }) })).json();
      if (j.colab_url) { window.open(j.colab_url, "_blank"); setStatus("Opened in Colab"); }
      else setStatus("Colab error: " + (j.error || "?"));
    } catch (e) { setStatus("Colab error: " + (e as Error).message); }
  }
  const cellClass = (col: string, v: unknown) =>
    col.includes("— Δ") && typeof v === "number" ? (v < 0 ? "text-red-600" : "text-emerald-700") : "";

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Table Builder</h1>
        <p className="mt-1 text-muted-foreground">
          Build custom tables of federal spending — pick a timeframe, group by any fields,
          aggregate, and get the exact code to reproduce every number.
        </p>
      </div>

      <Step n={1} title="Select a dataset">
        <div className="grid gap-3 sm:grid-cols-2">
          {DATASETS.map((d) => (
            <button key={d.value} onClick={() => setDataset(d.value)}
              className={`rounded-lg border p-4 text-left transition-colors ${dataset === d.value ? "border-primary bg-primary/5 ring-1 ring-primary" : "hover:bg-muted"}`}>
              <div className="flex items-center gap-2 font-medium">
                <span className={`flex h-4 w-4 items-center justify-center rounded-full border ${dataset === d.value ? "border-primary" : ""}`}>
                  {dataset === d.value && <span className="h-2 w-2 rounded-full bg-primary" />}
                </span>
                {d.label}
              </div>
            </button>
          ))}
        </div>
      </Step>

      <Step n={2} title="Select a timeframe" hint="Leave blank for all time. Tip: group by “Month” in step 3 to see every month in the range.">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm font-medium">Filter</span>
          <Select value={dateField} onValueChange={(v) => setDateField(v ?? "")}>
            <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
            <SelectContent>{Object.entries(DATE_FIELDS).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}</SelectContent>
          </Select>
          <span className="text-sm text-muted-foreground">between</span>
          <DateRangePicker value={aRange} onChange={setARange} placeholder="all dates" />
        </div>
      </Step>

      <Step n={3} title="Select table elements" hint="Group by one or more fields — they combine into a single table (GROUP BY a, b, …). Pick measures to aggregate.">
        <div className="space-y-4">
          <div>
            <Label className="mb-1.5 block">Group by</Label>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(DIMENSIONS).map(([k, v]) => (
                <Badge key={k} variant={rows.includes(k) ? "default" : "outline"} className="cursor-pointer" onClick={() => toggle(rows, k, setRows)}>{v}</Badge>
              ))}
            </div>
          </div>
          <div>
            <Label className="mb-1.5 block">Measures</Label>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(METRICS).map(([k, v]) => (
                <Badge key={k} variant={metrics.includes(k) ? "default" : "outline"} className="cursor-pointer" onClick={() => toggle(metrics, k, setMetrics)}>{v}</Badge>
              ))}
            </div>
          </div>
        </div>
      </Step>

      <Step n={4} title="Filters (optional)">
        <div className="space-y-3">
          {filters.map((f) => (
            <div key={f.id} className="space-y-1.5 rounded-md border p-2">
              <Select value={f.field} onValueChange={(v) => changeFilterField(f.id, v ?? "")}>
                <SelectTrigger className="h-8 w-full text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>{Object.entries(FILTER_FIELDS).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}</SelectContent>
              </Select>
              {f.options === null && <p className="text-xs text-muted-foreground">loading…</p>}
              {f.options && f.searchable && (
                <Input className="h-8 text-sm" placeholder="values, comma-separated" value={f.text} onChange={(e) => updateFilter(f.id, { text: e.target.value })} />
              )}
              {f.options && !f.searchable && (
                <div className="max-h-44 space-y-1 overflow-y-auto pr-1">
                  {f.options.map((o) => (
                    <label key={o.value} className="flex cursor-pointer items-center gap-2 text-sm">
                      <Checkbox checked={f.selected.includes(o.value)} onCheckedChange={() => updateFilter(f.id, { selected: f.selected.includes(o.value) ? f.selected.filter((x) => x !== o.value) : [...f.selected, o.value] })} />
                      {o.label}
                    </label>
                  ))}
                </div>
              )}
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={() => addFilter()}>+ filter</Button>
        </div>
      </Step>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="lg" onClick={() => run()}>Generate table</Button>
        <Button variant="outline" onClick={() => { navigator.clipboard.writeText(location.href); setStatus("Link copied"); }}>Copy link</Button>
        <Button variant="outline" onClick={records}>Download matching records (CSV)</Button>
        <span className="text-sm text-muted-foreground">{status}</span>
      </div>

      {tables.map((t) => (
        <Card key={t.dimension}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">{t.label}</CardTitle>
            <div className="flex gap-1">
              <Button variant="ghost" size="sm" onClick={() => setRepro(t.reproduce)}>Show code</Button>
              <Button variant="ghost" size="sm" onClick={() => downloadCSV(t.columns, t.data, t.dimension + ".csv")}>CSV</Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="max-h-[460px] overflow-auto rounded-md border">
              <Table>
                <TableHeader className="sticky top-0 bg-muted">
                  <TableRow>{t.columns.map((c, i) => <TableHead key={i} className={i < t.group_cols ? "" : "text-right"}>{c}</TableHead>)}</TableRow>
                </TableHeader>
                <TableBody>
                  {t.data.map((r, ri) => (
                    <TableRow key={ri}>
                      {r.map((v, ci) => (
                        <TableCell key={ci} className={`${ci < t.group_cols ? "font-medium" : "text-right tabular-nums"} ${cellClass(t.columns[ci], v)}`}>{fmtCell(v, t.columns[ci])}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      ))}

      {repro && (
        <Card>
          <CardHeader className="flex flex-row items-start justify-between space-y-0">
            <div>
              <CardTitle className="text-base">Reproduce this result</CardTitle>
              <p className="text-sm text-muted-foreground">This is the exact query the table above ran, against the public dataset — run it and you get the same numbers.</p>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button variant="outline" size="sm" onClick={openColab}>▶ Open in Colab</Button>
              <Button variant="outline" size="sm" onClick={() => {
                const a = document.createElement("a");
                a.href = URL.createObjectURL(new Blob([repro.python], { type: "text/plain" })); a.download = "reproduce.py"; a.click();
              }}>Download .py</Button>
            </div>
          </CardHeader>
          <CardContent>
            <pre className="overflow-auto whitespace-pre-wrap rounded-md bg-zinc-900 p-4 font-mono text-xs text-zinc-100">{repro.python}</pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
