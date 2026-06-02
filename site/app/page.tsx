"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

// Each tool is a purpose-built graphic backed entirely by a precomputed cube
// (site/public/precomputed/{dataset}.json) — you can modify it only within the dimensions
// we baked. Nothing is queried live; arbitrary analysis goes to the Table Builder (code).
const GREEN = "#2d6a4f";
type Metric = "obl" | "txn";

const DATASETS = [
  { value: "contracts", label: "Contracts (prime)" },
  { value: "assistance", label: "Assistance (grants/loans)" },
];

type Item = { label: string; obl: number; txn: number };
type Dim = { label: string; categorical: boolean; periods: Record<string, Item[]> };
type TS = { fy: string; agency: string; sub: string; obl: number; txn: number };
type Data = {
  years: string[];
  kpis: Record<string, { obl: number; txn: number }>;
  dims: Record<string, Dim>;
  timeseries: TS[];
};

const fmtUSD = (v: number) => {
  const a = Math.abs(v);
  if (a >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${Math.round(v).toLocaleString()}`;
};
const fmtNum = (v: number) => Math.round(v).toLocaleString();
const fmt = (m: Metric) => (m === "obl" ? fmtUSD : fmtNum);
const metricLabel = (m: Metric) => (m === "obl" ? "Obligations" : "Transactions");

function downloadCSV(rows: (string | number)[][], name: string) {
  const esc = (x: unknown) => (x == null ? "" : `"${String(x).replace(/"/g, '""')}"`);
  const csv = rows.map((r) => r.map(esc).join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = name; a.click();
}

/** A searchable single-select over a precomputed value list (OPM "Search …" style). */
function Typeahead({ label, value, options, onChange }: {
  label: string; value: string; options: string[]; onChange: (v: string) => void;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const shown = (q ? options.filter((o) => o.toLowerCase().includes(q.toLowerCase())) : options).slice(0, 200);
  return (
    <div className="min-w-[14rem] flex-1">
      <div className="mb-1 text-sm font-medium">{label}</div>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger className="flex h-9 w-full items-center justify-between rounded-md border bg-background px-3 text-sm shadow-xs hover:bg-muted">
          <span className={value ? "" : "text-muted-foreground"}>{value || `All ${label.toLowerCase()}`}</span>
          <span className="text-muted-foreground">▾</span>
        </PopoverTrigger>
        <PopoverContent className="w-72 p-2" align="start">
          <Input className="mb-2 h-8" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="max-h-64 space-y-0.5 overflow-y-auto">
            <button className="block w-full rounded px-2 py-1 text-left text-sm hover:bg-muted"
              onClick={() => { onChange(""); setOpen(false); }}>All {label.toLowerCase()}</button>
            {shown.map((o) => (
              <button key={o} className={`block w-full truncate rounded px-2 py-1 text-left text-sm hover:bg-muted ${o === value ? "bg-primary/10 font-medium" : ""}`}
                onClick={() => { onChange(o); setOpen(false); }}>{o}</button>
            ))}
            {shown.length === 0 && <p className="px-2 py-1 text-xs text-muted-foreground">no match</p>}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

function Toggle<T extends string>({ value, onChange, opts }: { value: T; onChange: (v: T) => void; opts: { v: T; label: string }[] }) {
  return (
    <div className="flex items-center gap-1 rounded-md border p-0.5">
      {opts.map((o) => (
        <Button key={o.v} size="sm" variant={value === o.v ? "default" : "ghost"} onClick={() => onChange(o.v)}>{o.label}</Button>
      ))}
    </div>
  );
}

/** Tool 1 — spending over time, filterable by agency / subagency + fiscal-year range. */
function SpendingOverTime({ data }: { data: Data }) {
  const [agency, setAgency] = useState("");
  const [sub, setSub] = useState("");
  const [metric, setMetric] = useState<Metric>("obl");
  const [asTable, setAsTable] = useState(false);
  const [from, setFrom] = useState(data.years[0]);
  const [to, setTo] = useState(data.years[data.years.length - 1]);

  const ts = data.timeseries ?? [];
  const agencies = useMemo(() => Array.from(new Set(ts.map((r) => r.agency))).sort(), [ts]);
  const subs = useMemo(() => Array.from(new Set(
    ts.filter((r) => !agency || r.agency === agency).map((r) => r.sub))).sort(), [ts, agency]);

  const rows = useMemo(() => {
    const byYear: Record<string, number> = {};
    for (const r of ts) {
      if (agency && r.agency !== agency) continue;
      if (sub && r.sub !== sub) continue;
      if (r.fy < from || r.fy > to) continue;
      byYear[r.fy] = (byYear[r.fy] || 0) + (metric === "obl" ? r.obl : r.txn);
    }
    return data.years.filter((y) => y >= from && y <= to).map((y) => ({ label: y, value: byYear[y] || 0 }));
  }, [data, agency, sub, from, to, metric]);

  const f = fmt(metric);
  const yearOpts = data.years;
  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">{metricLabel(metric)} over time</CardTitle>
          <div className="flex items-center gap-2">
            <Toggle value={metric} onChange={setMetric} opts={[{ v: "obl", label: "Obligations" }, { v: "txn", label: "Transactions" }]} />
            <Toggle value={asTable ? "t" : "c"} onChange={(v) => setAsTable(v === "t")} opts={[{ v: "c", label: "Graph" }, { v: "t", label: "Table" }]} />
            <Button size="sm" variant="outline" onClick={() => downloadCSV(
              [["fiscal_year", metric], ...rows.map((r) => [r.label, r.value])], "spending_over_time.csv")}>Export</Button>
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <Typeahead label="Agency" value={agency} options={agencies} onChange={(v) => { setAgency(v); setSub(""); }} />
          <Typeahead label="Sub-agency" value={sub} options={subs} onChange={setSub} />
          <div>
            <div className="mb-1 text-sm font-medium">Fiscal year range</div>
            <div className="flex items-center gap-1">
              <Select value={from} onValueChange={(v) => setFrom(v ?? from)}>
                <SelectTrigger className="h-9 w-24"><SelectValue /></SelectTrigger>
                <SelectContent>{yearOpts.map((y) => <SelectItem key={y} value={y}>{y}</SelectItem>)}</SelectContent>
              </Select>
              <span className="text-muted-foreground">–</span>
              <Select value={to} onValueChange={(v) => setTo(v ?? to)}>
                <SelectTrigger className="h-9 w-24"><SelectValue /></SelectTrigger>
                <SelectContent>{yearOpts.map((y) => <SelectItem key={y} value={y}>{y}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {asTable ? (
          <div className="max-h-[360px] overflow-auto rounded-md border">
            <Table>
              <TableHeader className="sticky top-0 bg-muted"><TableRow><TableHead>Fiscal year</TableHead><TableHead className="text-right">{metricLabel(metric)}</TableHead></TableRow></TableHeader>
              <TableBody>{rows.map((r) => <TableRow key={r.label}><TableCell>{r.label}</TableCell><TableCell className="text-right tabular-nums">{f(r.value)}</TableCell></TableRow>)}</TableBody>
            </Table>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={rows} margin={{ left: 12, right: 16, top: 4, bottom: 4 }}>
              <CartesianGrid stroke="#eee" />
              <XAxis dataKey="label" fontSize={12} stroke="#888" />
              <YAxis tickFormatter={(v) => f(v as number)} fontSize={12} stroke="#888" width={70} />
              <Tooltip formatter={(v) => f(v as number)} />
              <Line type="monotone" dataKey="value" stroke={GREEN} strokeWidth={2} dot={{ r: 2 }} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

/** Tools 2–5 — a precomputed breakdown, modifiable by year + metric. */
function Breakdown({ title, dim, years }: { title: string; dim: Dim; years: string[] }) {
  const [period, setPeriod] = useState("all");
  const [metric, setMetric] = useState<Metric>("obl");
  const [asTable, setAsTable] = useState(false);
  const items = useMemo(() => {
    const r = (dim.periods[period] || []).slice();
    r.sort((a, b) => (metric === "obl" ? b.obl - a.obl : b.txn - a.txn));
    return r.map((i) => ({ label: i.label, value: metric === "obl" ? i.obl : i.txn }));
  }, [dim, period, metric]);
  const f = fmt(metric);
  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">{title}</CardTitle>
          <div className="flex items-center gap-2">
            <Select value={period} onValueChange={(v) => setPeriod(v ?? "all")}>
              <SelectTrigger className="h-9 w-36"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All years</SelectItem>
                {years.slice().reverse().map((y) => <SelectItem key={y} value={y}>{`FY ${y}`}</SelectItem>)}
              </SelectContent>
            </Select>
            <Toggle value={metric} onChange={setMetric} opts={[{ v: "obl", label: "$" }, { v: "txn", label: "#" }]} />
            <Toggle value={asTable ? "t" : "c"} onChange={(v) => setAsTable(v === "t")} opts={[{ v: "c", label: "Graph" }, { v: "t", label: "Table" }]} />
            <Button size="sm" variant="outline" onClick={() => downloadCSV(
              [[dim.label, metric], ...items.map((r) => [r.label, r.value])], `${title.replace(/\W+/g, "_")}.csv`)}>Export</Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? <div className="flex h-72 items-center justify-center text-sm text-muted-foreground">no data</div>
          : asTable ? (
            <div className="max-h-[420px] overflow-auto rounded-md border">
              <Table>
                <TableHeader className="sticky top-0 bg-muted"><TableRow><TableHead>{dim.label}</TableHead><TableHead className="text-right">{metricLabel(metric)}</TableHead></TableRow></TableHeader>
                <TableBody>{items.map((r) => <TableRow key={r.label}><TableCell className="whitespace-nowrap">{r.label}</TableCell><TableCell className="text-right tabular-nums">{f(r.value)}</TableCell></TableRow>)}</TableBody>
              </Table>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(320, items.length * 22)}>
              <BarChart data={items} layout="vertical" margin={{ left: 8, right: 28, top: 4, bottom: 4 }}>
                <CartesianGrid horizontal={false} stroke="#eee" />
                <XAxis type="number" tickFormatter={(v) => f(v as number)} fontSize={11} stroke="#888" />
                <YAxis type="category" dataKey="label" width={220} fontSize={11} stroke="#555" interval={0}
                  tickFormatter={(v: string) => (v.length > 32 ? v.slice(0, 31) + "…" : v)} />
                <Tooltip formatter={(v) => f(v as number)} labelFormatter={(l) => String(l)} cursor={{ fill: "rgba(45,106,79,0.06)" }} />
                <Bar dataKey="value" fill={GREEN} radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
      </CardContent>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 border-t pt-8">
      <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

export default function Explorer() {
  const [dataset, setDataset] = useState("contracts");
  const [data, setData] = useState<Data | null>(null);
  useEffect(() => {
    setData(null);
    fetch(`/precomputed/${dataset}.json`).then((r) => r.json()).then(setData).catch(() => setData(null));
  }, [dataset]);

  const kpi = data?.kpis["all"];
  const dsLabel = DATASETS.find((d) => d.value === dataset)?.label ?? dataset;
  const dim = (k: string) => data?.dims[k];

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <h1 className="text-2xl font-semibold tracking-tight">Federal Spending Explorer</h1>
          <p className="mt-1 text-muted-foreground">
            Twenty years of federal {dataset === "contracts" ? "contract" : "assistance"} awards (FY2007–2026),
            from the public USAspending Award Data Archive. Explore the curated views below, or{" "}
            <Link href="/table-builder" className="underline hover:text-foreground">build your own query</Link> for anything else.
          </p>
        </div>
        <Select value={dataset} onValueChange={(v) => setDataset(v ?? "contracts")}>
          <SelectTrigger className="h-9 w-56"><SelectValue /></SelectTrigger>
          <SelectContent>{DATASETS.map((d) => <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>)}</SelectContent>
        </Select>
      </div>

      {/* headline numbers */}
      <div className="grid gap-4 sm:grid-cols-3">
        {[
          { label: "Total obligations, FY2007–2026", value: kpi ? fmtUSD(kpi.obl) : "" },
          { label: "Transactions", value: kpi ? fmtNum(kpi.txn) : "" },
          { label: "Avg per transaction", value: kpi && kpi.txn ? fmtUSD(kpi.obl / kpi.txn) : "" },
        ].map((t) => (
          <Card key={t.label}><CardContent className="py-4">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t.label}</div>
            {data ? <div className="mt-1 text-2xl font-semibold tabular-nums">{t.value}</div>
                  : <div className="mt-2 h-7 w-28 animate-pulse rounded bg-muted" />}
          </CardContent></Card>
        ))}
      </div>

      {!data ? (
        <div className="h-96 animate-pulse rounded-xl bg-muted/50" />
      ) : (
        <>
          <Section title="How spending has changed over time">
            <p className="max-w-3xl text-sm text-muted-foreground">
              Total {dsLabel.toLowerCase()} obligations by fiscal year. Narrow to a single agency or sub-agency,
              or a range of years, to see how a corner of the government has grown or shrunk.
            </p>
            <SpendingOverTime data={data} />
          </Section>

          <Section title="Who receives the money">
            <p className="max-w-3xl text-sm text-muted-foreground">The largest recipients of federal {dataset === "contracts" ? "contract" : "assistance"} dollars.</p>
            {dim("recipient") && <Breakdown title="Top recipients" dim={dim("recipient")!} years={data.years} />}
          </Section>

          <Section title="What it buys, and where">
            {dim("naics") && <Breakdown title="Top industries (NAICS)" dim={dim("naics")!} years={data.years} />}
            {dim("psc") && <Breakdown title="Top products & services (PSC)" dim={dim("psc")!} years={data.years} />}
            {dim("state") && <Breakdown title="By recipient state" dim={dim("state")!} years={data.years} />}
          </Section>

          {(dim("competition") || dim("set_aside") || dim("business_size")) && (
            <Section title="How awards are made">
              {dim("competition") && <Breakdown title="Competition" dim={dim("competition")!} years={data.years} />}
              {dim("set_aside") && <Breakdown title="Set-aside type" dim={dim("set_aside")!} years={data.years} />}
              {dim("business_size") && <Breakdown title="Business size" dim={dim("business_size")!} years={data.years} />}
            </Section>
          )}

          <p className="border-t pt-6 text-sm text-muted-foreground">
            These are curated views. For arbitrary breakdowns, filters, and all fields, the{" "}
            <Link href="/table-builder" className="underline hover:text-foreground">Table Builder</Link>{" "}
            generates ready-to-run code (Python / Colab) against the full published dataset.
          </p>
        </>
      )}
    </div>
  );
}
