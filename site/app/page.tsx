"use client";

import { useEffect, useMemo, useState } from "react";
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

// The dashboard reads a small precomputed file (site/public/precomputed/{dataset}.json) —
// no live querying. Everything shown here was aggregated offline from the full archive.
const GREEN = "#2d6a4f";
const HF_SERVE = "hf://datasets/abigailhaddad/usaspending-bulk-awards/serve";

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

function Trend({ data, metric }: { data: Data; metric: "obl" | "txn" }) {
  const rows = data.trend.map((t) => ({ label: t.fy, value: metric === "obl" ? t.obl : t.txn }));
  const fmt = metric === "obl" ? fmtUSD : fmtNum;
  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="text-base">
        {metric === "obl" ? "Obligations" : "Transactions"} by fiscal year
      </CardTitle></CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={rows} margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
            <CartesianGrid vertical={false} stroke="#eee" />
            <XAxis dataKey="label" fontSize={12} stroke="#888" />
            <YAxis tickFormatter={(v) => fmt(v as number)} fontSize={12} stroke="#888" width={64} />
            <Tooltip formatter={(v) => fmt(v as number)} cursor={{ fill: "rgba(45,106,79,0.06)" }} />
            <Bar dataKey="value" fill={GREEN} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

function Breakdown({ dim, period, metric, asTable }: {
  dim: Dim; period: string; metric: "obl" | "txn"; asTable: boolean;
}) {
  const fmt = metric === "obl" ? fmtUSD : fmtNum;
  const items = useMemo(() => {
    const rows = (dim.periods[period] || []).slice();
    rows.sort((a, b) => (metric === "obl" ? b.obl - a.obl : b.txn - a.txn));
    return rows;
  }, [dim, period, metric]);
  const rows = items.map((i) => ({ label: i.label, value: metric === "obl" ? i.obl : i.txn }));

  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="text-base">{dim.label}</CardTitle></CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <div className="flex h-[300px] items-center justify-center text-sm text-muted-foreground">no data for this period</div>
        ) : asTable ? (
          <div className="max-h-[340px] overflow-auto rounded-md border">
            <Table>
              <TableHeader className="sticky top-0 bg-muted"><TableRow>
                <TableHead>{dim.label}</TableHead>
                <TableHead className="text-right">{metric === "obl" ? "Obligations" : "Transactions"}</TableHead>
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
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(300, rows.length * 24)}>
            <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 28, top: 4, bottom: 4 }}>
              <CartesianGrid horizontal={false} stroke="#eee" />
              <XAxis type="number" tickFormatter={(v) => fmt(v as number)} fontSize={11} stroke="#888" />
              <YAxis type="category" dataKey="label" width={210} fontSize={11} stroke="#555" interval={0}
                tickFormatter={(v: string) => (v.length > 32 ? v.slice(0, 31) + "…" : v)} />
              <Tooltip formatter={(v) => fmt(v as number)} labelFormatter={(l) => String(l)} cursor={{ fill: "rgba(45,106,79,0.06)" }} />
              <Bar dataKey="value" fill={GREEN} radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

function ColabCard({ dataset, period }: { dataset: string; period: string }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const yr = period === "all" ? "2025" : period;
  const sql =
    `SELECT awarding_agency_name, sum(TRY_CAST(federal_action_obligation AS DOUBLE)) AS obligations, count(*) AS transactions\n` +
    `FROM read_parquet('${HF_SERVE}/${dataset}/*.parquet', union_by_name=true)\n` +
    `WHERE action_date_fiscal_year = '${yr}'\n` +
    `GROUP BY 1 ORDER BY obligations DESC LIMIT 25`;
  async function open() {
    setBusy(true); setErr("");
    try {
      const r = await fetch("/api/colab", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql, title: "USAspending — custom analysis" }),
      });
      const j = await r.json();
      if (j.colab_url) window.open(j.colab_url, "_blank");
      else setErr(j.error || "could not create notebook");
    } catch (e) { setErr(String(e)); }
    setBusy(false);
  }
  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="text-base">Build your own analysis</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">
          Need a cut this dashboard doesn’t show? Open a ready-to-run Colab notebook that queries the full
          published dataset (all {dataset === "contracts" ? "297" : "112"} fields, every year) with DuckDB —
          edit the query and run it in your browser, no setup.
        </p>
        <pre className="overflow-auto rounded-md bg-muted p-3 text-xs leading-relaxed">{sql}</pre>
        <div className="flex items-center gap-3">
          <Button size="sm" onClick={open} disabled={busy}>{busy ? "Creating…" : "Open in Colab"}</Button>
          {err && <span className="text-sm text-red-600">{err}</span>}
        </div>
      </CardContent>
    </Card>
  );
}

export default function Explorer() {
  const [dataset, setDataset] = useState("contracts");
  const [data, setData] = useState<Data | null>(null);
  const [period, setPeriod] = useState("all");
  const [metric, setMetric] = useState<"obl" | "txn">("obl");
  const [asTable, setAsTable] = useState(false);

  useEffect(() => {
    setData(null);
    fetch(`/precomputed/${dataset}.json`).then((r) => r.json()).then(setData).catch(() => setData(null));
  }, [dataset]);

  const kpi = data ? (data.kpis[period] ?? data.kpis["all"]) : undefined;
  const periodLabel = period === "all" ? "All years" : `FY ${period}`;
  const dimKeys = data ? Object.keys(data.dims) : [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Spending Explorer</h1>
        <p className="mt-1 text-muted-foreground">
          Curated views of federal contract & assistance spending. Pick a dataset, fiscal year, and measure.
        </p>
      </div>

      {/* controls */}
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

      {!data ? (
        <div className="grid gap-6 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-[340px] animate-pulse rounded-xl bg-muted/50" />)}
        </div>
      ) : (
        <>
          <Trend data={data} metric={metric} />
          <div className="grid gap-6 lg:grid-cols-2">
            {dimKeys.map((k) => (
              <Breakdown key={k} dim={data.dims[k]} period={period} metric={metric} asTable={asTable} />
            ))}
          </div>
          <ColabCard dataset={dataset} period={period} />
        </>
      )}
    </div>
  );
}
