"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { DateRange } from "react-day-picker";
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { DateRangePicker } from "@/components/date-range";
import { MultiSelect } from "@/components/multi-select";
import { FieldPicker } from "@/components/field-picker";
import { DATASETS, FILTER_FIELDS } from "@/lib/registry";

const GREEN = "#2d6a4f";
type Row = { label: string; value: number };
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const money = (v: number) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}B`;

async function agg(dataset: string, dim: string, top: number | undefined, qs: string): Promise<Row[]> {
  let u = `/api/table?dataset=${dataset}&rows=${dim}&metric=obligations`;
  if (top) u += `&top=${top}`;
  if (qs) u += `&${qs}`;
  const j = await (await fetch(u)).json();
  if (!j.tables?.[0]) return [];
  return j.tables[0].data
    .filter((r: unknown[]) => r[0] != null && r[1] != null)
    .map((r: [string, number]) => ({ label: String(r[0]), value: r[1] / 1e9 }));
}

function Panel({
  title, dataset, dim, top, qs, horizontal = true, builderDim,
}: { title: string; dataset: string; dim: string; top?: number; qs: string; horizontal?: boolean; builderDim?: string }) {
  const [data, setData] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  useEffect(() => {
    let on = true; setLoading(true);
    agg(dataset, dim, top, qs).then((d) => { if (on) { setData(d); setLoading(false); } });
    return () => { on = false; };
  }, [dataset, dim, top, qs]);
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
        {builderDim && (
          <Button variant="ghost" size="sm"
            onClick={() => router.push(`/?dataset=${dataset}&rows=${builderDim}&metric=obligations${qs ? `&${qs}` : ""}`)}>
            open in builder →
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {loading ? <div className="flex h-[320px] items-center justify-center text-sm text-muted-foreground">loading…</div>
          : data.length === 0 ? <div className="flex h-[320px] items-center justify-center text-sm text-muted-foreground">no data for these filters</div>
          : horizontal ? (
            <ResponsiveContainer width="100%" height={Math.max(320, data.length * 26)}>
              <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
                <CartesianGrid horizontal={false} stroke="#eee" />
                <XAxis type="number" tickFormatter={(v) => `$${v}B`} fontSize={12} stroke="#888" />
                <YAxis type="category" dataKey="label" width={240} fontSize={12} stroke="#555" interval={0}
                  tickFormatter={(v: string) => (v.length > 38 ? v.slice(0, 37) + "…" : v)} />
                <Tooltip formatter={(v: number) => money(v)} labelFormatter={(l) => String(l)} cursor={{ fill: "rgba(45,106,79,0.06)" }} />
                <Bar dataKey="value" fill={GREEN} radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={data} margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
                <CartesianGrid vertical={false} stroke="#eee" />
                <XAxis dataKey="label" fontSize={12} stroke="#888" />
                <YAxis tickFormatter={(v) => `$${v}B`} fontSize={12} stroke="#888" />
                <Tooltip formatter={(v: number) => money(v)} cursor={{ fill: "rgba(45,106,79,0.06)" }} />
                <Bar dataKey="value" fill={GREEN} radius={[3, 3, 0, 0]}>{data.map((_, i) => <Cell key={i} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
      </CardContent>
    </Card>
  );
}

function fmtCell(v: unknown, col: string) {
  if (v == null) return "";
  if (typeof v === "number") {
    if (col.includes("obligation")) return `$${(v / 1e6).toLocaleString(undefined, { maximumFractionDigits: 2 })}M`;
    return v.toLocaleString();
  }
  return String(v);
}

function ResultsTable({ dataset, qs }: { dataset: string; qs: string }) {
  const [cols, setCols] = useState<string[]>([]);
  const [rows, setRows] = useState<(string | number | null)[][]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  useEffect(() => {
    let on = true; setLoading(true);
    fetch(`/api/detail?dataset=${dataset}&limit=200${qs ? `&${qs}` : ""}`)
      .then((r) => r.json()).then((j) => { if (on) { setCols(j.columns || []); setRows(j.data || []); setLoading(false); } });
    return () => { on = false; };
  }, [dataset, qs]);

  async function downloadAll() {
    setStatus("Fetching all matching records…");
    const j = await (await fetch(`/api/detail?dataset=${dataset}${qs ? `&${qs}` : ""}`)).json();
    const esc = (x: unknown) => (x == null ? "" : `"${String(x).replace(/"/g, '""')}"`);
    const csv = [j.columns.map(esc).join(","), ...j.data.map((r: unknown[]) => r.map(esc).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "records.csv"; a.click();
    setStatus(`${j.count} records${j.truncated ? " (capped at 100k)" : ""} downloaded`);
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="text-base">Matching records</CardTitle>
          <p className="text-sm text-muted-foreground">Individual awards behind the charts above (preview of the first 200).</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">{status}</span>
          <Button variant="outline" size="sm" onClick={downloadAll}>Download all (CSV)</Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="max-h-[520px] overflow-auto rounded-md border">
          <Table>
            <TableHeader className="sticky top-0 bg-muted">
              <TableRow>{cols.map((c) => <TableHead key={c} className="whitespace-nowrap">{c}</TableHead>)}</TableRow>
            </TableHeader>
            <TableBody>
              {loading && <TableRow><TableCell colSpan={cols.length || 1} className="text-muted-foreground">loading…</TableCell></TableRow>}
              {!loading && rows.length === 0 && <TableRow><TableCell colSpan={cols.length || 1} className="text-muted-foreground">no records</TableCell></TableRow>}
              {rows.map((r, ri) => (
                <TableRow key={ri}>{r.map((v, ci) => (
                  <TableCell key={ci} className="whitespace-nowrap">{fmtCell(v, cols[ci])}</TableCell>
                ))}</TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

export default function Explorer() {
  const [dataset, setDataset] = useState("contracts");
  const [range, setRange] = useState<DateRange | undefined>();
  const [filters, setFilters] = useState<Record<string, string[]>>({});
  const [labels, setLabels] = useState<Record<string, string>>({});

  const flabel = (field: string) => labels[field] || FILTER_FIELDS[field] || field.replace(/_/g, " ");
  const setVals = (field: string, vals: string[]) => setFilters((f) => ({ ...f, [field]: vals }));
  const removeField = (field: string) => setFilters((f) => { const n = { ...f }; delete n[field]; return n; });
  const removeValue = (field: string, v: string) => setFilters((f) => {
    const vals = (f[field] || []).filter((x) => x !== v);
    if (!vals.length) { const n = { ...f }; delete n[field]; return n; }
    return { ...f, [field]: vals };
  });
  const clearAll = () => { setRange(undefined); setFilters({}); };

  const p = new URLSearchParams();
  if (range?.from && range?.to) p.set("periodA", `${iso(range.from)}..${iso(range.to)}`);
  for (const [field, vals] of Object.entries(filters)) if (vals.length) p.set(`filter_${field}`, vals.join("|"));
  const qs = p.toString();

  const activeFields = Object.keys(filters);
  const chips = Object.entries(filters).flatMap(([field, vals]) => vals.map((v) => ({ field, v })));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Spending Explorer</h1>
        <p className="mt-1 text-muted-foreground">Filter federal spending any way you like, then explore the charts and the matching records.</p>
      </div>

      {/* filter panel */}
      <Card className="sticky top-[57px] z-10">
        <CardContent className="space-y-3 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <Select value={dataset} onValueChange={setDataset}>
              <SelectTrigger className="h-9 w-44"><SelectValue /></SelectTrigger>
              <SelectContent>{DATASETS.map((d) => <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>)}</SelectContent>
            </Select>
            <DateRangePicker value={range} onChange={setRange} placeholder="All dates" />
            {activeFields.map((field) => (
              <span key={field} className="inline-flex items-center">
                <MultiSelect field={field} dataset={dataset} label={flabel(field)}
                  value={filters[field]} onChange={(v) => setVals(field, v)} />
                <button className="ml-1 text-muted-foreground hover:text-foreground" onClick={() => removeField(field)} title="remove filter">✕</button>
              </span>
            ))}
            <FieldPicker dataset={dataset} exclude={activeFields}
              onPick={(field, label) => { setLabels((l) => ({ ...l, [field]: label })); setVals(field, filters[field] || []); }} />
          </div>
          {(chips.length > 0 || range?.from) && (
            <div className="flex flex-wrap items-center gap-1.5 border-t pt-2">
              {range?.from && range?.to && (
                <Badge variant="secondary" className="gap-1">{iso(range.from)} – {iso(range.to)}
                  <button onClick={() => setRange(undefined)}>✕</button></Badge>
              )}
              {chips.map(({ field, v }) => (
                <Badge key={field + v} variant="secondary" className="gap-1">
                  <span className="text-muted-foreground">{flabel(field)}:</span> {v}
                  <button onClick={() => removeValue(field, v)}>✕</button>
                </Badge>
              ))}
              <button className="ml-1 text-xs text-muted-foreground underline" onClick={clearAll}>clear all</button>
            </div>
          )}
        </CardContent>
      </Card>

      <Panel title="Obligations by fiscal year" dataset={dataset} dim="fiscal_year" qs={qs} horizontal={false} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Top awarding agencies" dataset={dataset} dim="awarding_agency" top={15} qs={qs} builderDim="awarding_agency" />
        <Panel title="Top recipients" dataset={dataset} dim="recipient" top={15} qs={qs} builderDim="recipient" />
        <Panel title="Top states" dataset={dataset} dim="state" top={15} qs={qs} builderDim="state" />
        <Panel title="Competition" dataset={dataset} dim="extent_competed" qs={qs} builderDim="extent_competed" />
        <Panel title="Top products & services" dataset={dataset} dim="psc_desc" top={15} qs={qs} builderDim="psc_desc" />
        <Panel title="Top industries (NAICS)" dataset={dataset} dim="naics_desc" top={15} qs={qs} builderDim="naics_desc" />
      </div>

      <ResultsTable dataset={dataset} qs={qs} />
    </div>
  );
}
