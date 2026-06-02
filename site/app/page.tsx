"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

// Interactive curated explorer (data.opm.gov style): you pick the cut — dataset, fiscal
// year, measure, and what to break down by — and the chart updates in place. All values
// come from a small precomputed file (site/public/precomputed/{dataset}.json); nothing is
// queried live. Arbitrary queries live in the Table Builder, which emits runnable code.
const GREEN = "#2d6a4f";

const DATASETS = [
  { value: "contracts", label: "Contracts (prime)" },
  { value: "assistance", label: "Assistance (grants/loans)" },
];

type Item = { label: string; obl: number; txn: number };
type Dim = { label: string; categorical: boolean; periods: Record<string, Item[]> };
type Data = {
  years: string[];
  trend: { fy: string; obl: number; txn: number }[];
  kpis: Record<string, { obl: number; txn: number }>;
  dims: Record<string, Dim>;
};

const fmtUSD = (v: number) => {
  const a = Math.abs(v);
  if (a >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${Math.round(v).toLocaleString()}`;
};
const fmtNum = (v: number) => Math.round(v).toLocaleString();

/** Shared chart-or-table renderer for a set of {label,value} rows. */
function View({ rows, metric, asTable, head, vertical }: {
  rows: { label: string; value: number }[]; metric: "obl" | "txn"; asTable: boolean; head: string; vertical?: boolean;
}) {
  const fmt = metric === "obl" ? fmtUSD : fmtNum;
  const metricLabel = metric === "obl" ? "Obligations" : "Transactions";
  if (rows.length === 0)
    return <div className="flex h-[320px] items-center justify-center text-sm text-muted-foreground">no data for this selection</div>;
  if (asTable)
    return (
      <div className="max-h-[480px] overflow-auto rounded-md border">
        <Table>
          <TableHeader className="sticky top-0 bg-muted"><TableRow>
            <TableHead>{head}</TableHead>
            <TableHead className="text-right">{metricLabel}</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.label}>
                <TableCell className="whitespace-nowrap">{r.label}</TableCell>
                <TableCell className="text-right tabular-nums">{fmt(r.value)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    );
  if (vertical)
    return (
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={rows} margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
          <CartesianGrid vertical={false} stroke="#eee" />
          <XAxis dataKey="label" fontSize={12} stroke="#888" />
          <YAxis tickFormatter={(v) => fmt(v as number)} fontSize={12} stroke="#888" width={64} />
          <Tooltip formatter={(v) => fmt(v as number)} cursor={{ fill: "rgba(45,106,79,0.06)" }} />
          <Bar dataKey="value" fill={GREEN} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  return (
    <ResponsiveContainer width="100%" height={Math.max(340, rows.length * 24)}>
      <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 28, top: 4, bottom: 4 }}>
        <CartesianGrid horizontal={false} stroke="#eee" />
        <XAxis type="number" tickFormatter={(v) => fmt(v as number)} fontSize={11} stroke="#888" />
        <YAxis type="category" dataKey="label" width={230} fontSize={11} stroke="#555" interval={0}
          tickFormatter={(v: string) => (v.length > 34 ? v.slice(0, 33) + "…" : v)} />
        <Tooltip formatter={(v) => fmt(v as number)} labelFormatter={(l) => String(l)} cursor={{ fill: "rgba(45,106,79,0.06)" }} />
        <Bar dataKey="value" fill={GREEN} radius={[0, 3, 3, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export default function Explorer() {
  const [dataset, setDataset] = useState("contracts");
  const [data, setData] = useState<Data | null>(null);
  const [dim, setDim] = useState("awarding_agency");
  const [period, setPeriod] = useState("all");
  const [metric, setMetric] = useState<"obl" | "txn">("obl");
  const [asTable, setAsTable] = useState(false);

  useEffect(() => {
    setData(null);
    fetch(`/precomputed/${dataset}.json`).then((r) => r.json()).then((d: Data) => {
      setData(d);
      if (!d.dims[dim]) setDim(Object.keys(d.dims)[0]);
    }).catch(() => setData(null));
  }, [dataset]); // eslint-disable-line react-hooks/exhaustive-deps

  const kpi = data ? (data.kpis[period] ?? data.kpis["all"]) : undefined;
  const periodLabel = period === "all" ? "All years" : `FY ${period}`;

  const trendRows = useMemo(
    () => (data?.trend ?? []).map((t) => ({ label: t.fy, value: metric === "obl" ? t.obl : t.txn })),
    [data, metric]);

  const breakdownRows = useMemo(() => {
    const items = (data?.dims[dim]?.periods[period] ?? []).slice();
    items.sort((a, b) => (metric === "obl" ? b.obl - a.obl : b.txn - a.txn));
    return items.map((i) => ({ label: i.label, value: metric === "obl" ? i.obl : i.txn }));
  }, [data, dim, period, metric]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Spending Explorer</h1>
        <p className="mt-1 text-muted-foreground">
          Federal contract & assistance spending. Choose a dataset, fiscal year, and measure, then break it down.
          Need a custom cut? <Link href="/table-builder" className="underline hover:text-foreground">build a query</Link>.
        </p>
      </div>

      {/* global controls */}
      <Card className="sticky top-[57px] z-10">
        <CardContent className="flex flex-wrap items-center gap-2 py-3">
          <Select value={dataset} onValueChange={(v) => setDataset(v ?? "contracts")}>
            <SelectTrigger className="h-9 w-52"><SelectValue /></SelectTrigger>
            <SelectContent>{DATASETS.map((d) => <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>)}</SelectContent>
          </Select>
          <Select value={period} onValueChange={(v) => setPeriod(v ?? "all")}>
            <SelectTrigger className="h-9 w-40"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All years</SelectItem>
              {(data?.years ?? []).slice().reverse().map((y) => <SelectItem key={y} value={y}>{`FY ${y}`}</SelectItem>)}
            </SelectContent>
          </Select>
          <div className="ml-auto flex items-center gap-1 rounded-md border p-0.5">
            <Button size="sm" variant={metric === "obl" ? "default" : "ghost"} onClick={() => setMetric("obl")}>Obligations</Button>
            <Button size="sm" variant={metric === "txn" ? "default" : "ghost"} onClick={() => setMetric("txn")}>Transactions</Button>
          </div>
          <div className="flex items-center gap-1 rounded-md border p-0.5">
            <Button size="sm" variant={!asTable ? "default" : "ghost"} onClick={() => setAsTable(false)}>Chart</Button>
            <Button size="sm" variant={asTable ? "default" : "ghost"} onClick={() => setAsTable(true)}>Table</Button>
          </div>
        </CardContent>
      </Card>

      {/* KPI tiles */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Total obligations", value: kpi ? fmtUSD(kpi.obl) : "" },
          { label: "Transactions", value: kpi ? fmtNum(kpi.txn) : "" },
          { label: "Avg per transaction", value: kpi && kpi.txn ? fmtUSD(kpi.obl / kpi.txn) : "" },
          { label: "Period", value: periodLabel },
        ].map((t) => (
          <Card key={t.label}><CardContent className="py-4">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t.label}</div>
            {data ? <div className="mt-1 text-2xl font-semibold tabular-nums">{t.value || "—"}</div>
                  : <div className="mt-2 h-7 w-28 animate-pulse rounded bg-muted" />}
          </CardContent></Card>
        ))}
      </div>

      {/* over time */}
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">
          {metric === "obl" ? "Obligations" : "Transactions"} over time
        </CardTitle></CardHeader>
        <CardContent>
          {data ? <View rows={trendRows} metric={metric} asTable={asTable} head="Fiscal year" vertical />
                : <div className="h-[300px] animate-pulse rounded bg-muted/50" />}
        </CardContent>
      </Card>

      {/* reconfigurable breakdown — the interactive core */}
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center gap-3 space-y-0 pb-2">
          <CardTitle className="text-base">Break down by</CardTitle>
          <Select value={dim} onValueChange={(v) => v && setDim(v)}>
            <SelectTrigger className="h-9 w-56"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(data?.dims ?? {}).map(([k, d]) => <SelectItem key={k} value={k}>{d.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <span className="text-sm text-muted-foreground">· {periodLabel} · {metric === "obl" ? "obligations" : "transactions"}</span>
        </CardHeader>
        <CardContent>
          {data ? <View rows={breakdownRows} metric={metric} asTable={asTable} head={data.dims[dim]?.label ?? "Category"} />
                : <div className="h-[400px] animate-pulse rounded bg-muted/50" />}
        </CardContent>
      </Card>

      <p className="text-sm text-muted-foreground">
        These are curated views. For arbitrary breakdowns, filters, and all fields, the{" "}
        <Link href="/table-builder" className="underline hover:text-foreground">Table Builder</Link>{" "}
        generates a ready-to-run query (Python / Colab) against the full published dataset.
      </p>
    </div>
  );
}
