"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Bar, BarChart, CartesianGrid, LabelList, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
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

const GREEN = "#2d6a4f";
const TOP_N = 15; // breakdown bars shown (avoids a long tail of invisible ~0 bars)
type Metric = "obl" | "txn";

type Item = { label: string; obl: number; txn: number };
type Dim = { label: string; categorical: boolean; periods: Record<string, Item[]> };
type TS = { fy: string; agency: string; sub: string; obl: number; txn: number };
type Agency = { name: string; slug: string };
type Data = {
  years: string[];
  kpis: Record<string, { obl: number; txn: number }>;
  dims: Record<string, Dim>;
  timeseries: TS[];
  agencies?: Agency[];
};

// US state/territory codes -> full names (the state dim stores recipient_state_code)
const STATE_NAMES: Record<string, string> = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado",
  CT: "Connecticut", DE: "Delaware", DC: "District of Columbia", FL: "Florida", GA: "Georgia",
  HI: "Hawaii", ID: "Idaho", IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky",
  LA: "Louisiana", ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota",
  MS: "Mississippi", MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada", NH: "New Hampshire",
  NJ: "New Jersey", NM: "New Mexico", NY: "New York", NC: "North Carolina", ND: "North Dakota",
  OH: "Ohio", OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina",
  SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia",
  WA: "Washington", WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming",
  PR: "Puerto Rico", GU: "Guam", VI: "U.S. Virgin Islands", AS: "American Samoa", MP: "Northern Mariana Islands",
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

function Typeahead({ label, value, options, onChange, allLabel }: {
  label: string; value: string; options: string[]; onChange: (v: string) => void; allLabel?: string;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const all = allLabel || `All ${label.toLowerCase()}`;
  const shown = (q ? options.filter((o) => o.toLowerCase().includes(q.toLowerCase())) : options).slice(0, 200);
  return (
    <div className="min-w-[14rem] flex-1">
      <div className="mb-1 text-sm font-medium">{label}</div>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger className="flex h-9 w-full items-center justify-between rounded border bg-background px-3 text-sm hover:bg-muted">
          <span className={value ? "" : "text-muted-foreground"}>{value || all}</span>
          <span className="text-muted-foreground">▾</span>
        </PopoverTrigger>
        <PopoverContent className="w-72 p-2" align="start">
          <Input className="mb-2 h-8" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="max-h-64 space-y-0.5 overflow-y-auto">
            <button className="block w-full rounded px-2 py-1 text-left text-sm hover:bg-muted"
              onClick={() => { onChange(""); setOpen(false); }}>{all}</button>
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
    <div className="flex items-center gap-1 rounded border p-0.5">
      {opts.map((o) => (
        <Button key={o.v} size="sm" variant={value === o.v ? "default" : "ghost"} onClick={() => onChange(o.v)}>{o.label}</Button>
      ))}
    </div>
  );
}

function SpendingOverTime({ data }: { data: Data }) {
  const [sub, setSub] = useState("");
  const [metric, setMetric] = useState<Metric>("obl");
  const [asTable, setAsTable] = useState(false);
  const [from, setFrom] = useState(data.years[0]);
  const [to, setTo] = useState(data.years[data.years.length - 1]);

  // agency is filtered at the page level (this tool's `data` is already scoped); we offer
  // the finer sub-agency cut here, plus the fiscal-year range.
  const ts = data.timeseries ?? [];
  const subs = useMemo(() => Array.from(new Set(ts.map((r) => r.sub))).sort(), [ts]);

  const rows = useMemo(() => {
    const byYear: Record<string, number> = {};
    for (const r of ts) {
      if (sub && r.sub !== sub) continue;
      if (r.fy < from || r.fy > to) continue;
      byYear[r.fy] = (byYear[r.fy] || 0) + (metric === "obl" ? r.obl : r.txn);
    }
    return data.years.filter((y) => y >= from && y <= to).map((y) => ({ label: y, value: byYear[y] || 0 }));
  }, [ts, data.years, sub, from, to, metric]);

  const f = fmt(metric);
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
          <Typeahead label="Sub-agency" value={sub} options={subs} onChange={setSub} allLabel="All sub-agencies" />
          <div>
            <div className="mb-1 text-sm font-medium">Fiscal year range</div>
            <div className="flex items-center gap-1">
              <Select value={from} onValueChange={(v) => setFrom(v ?? from)}>
                <SelectTrigger className="h-9 w-24"><SelectValue /></SelectTrigger>
                <SelectContent>{data.years.map((y) => <SelectItem key={y} value={y}>{y}</SelectItem>)}</SelectContent>
              </Select>
              <span className="text-muted-foreground">–</span>
              <Select value={to} onValueChange={(v) => setTo(v ?? to)}>
                <SelectTrigger className="h-9 w-24"><SelectValue /></SelectTrigger>
                <SelectContent>{data.years.map((y) => <SelectItem key={y} value={y}>{y}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {asTable ? (
          <div className="max-h-[360px] overflow-auto rounded border">
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
        <p className="mt-2 text-xs text-muted-foreground">
          FY{data.years[data.years.length - 1]} is a partial year (still in progress) — the most recent point is incomplete and will keep rising.
        </p>
      </CardContent>
    </Card>
  );
}

function Breakdown({ title, dim, years, labelMap }: {
  title: string; dim: Dim; years: string[]; labelMap?: Record<string, string>;
}) {
  const [period, setPeriod] = useState("all");
  const [metric, setMetric] = useState<Metric>("obl");
  const [asTable, setAsTable] = useState(false);
  const disp = (v: string) => (labelMap && labelMap[v]) || v;
  const full = dim.periods[period] || [];
  const truncated = full.length > TOP_N;
  const items = useMemo(() => {
    const r = full.slice();
    r.sort((a, b) => (metric === "obl" ? b.obl - a.obl : b.txn - a.txn));
    return r.slice(0, TOP_N).map((i) => ({ label: disp(i.label), value: metric === "obl" ? i.obl : i.txn }));
  }, [dim, period, metric, labelMap]);
  const f = fmt(metric);
  const periodText = period === "all"
    ? `All years · FY${years[0]}–${years[years.length - 1]}`
    : `FY ${period}`;
  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base">
              {title}
              {truncated && <span className="ml-2 align-middle text-xs font-normal text-muted-foreground">top {TOP_N} by {metric === "obl" ? "$" : "awards"}</span>}
            </CardTitle>
            <div className="text-xs text-muted-foreground">{periodText}</div>
          </div>
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
            <div className="max-h-[420px] overflow-auto rounded border">
              <Table>
                <TableHeader className="sticky top-0 bg-muted"><TableRow><TableHead>{dim.label}</TableHead><TableHead className="text-right">{metricLabel(metric)}</TableHead></TableRow></TableHeader>
                <TableBody>{items.map((r) => <TableRow key={r.label}><TableCell className="whitespace-nowrap">{r.label}</TableCell><TableCell className="text-right tabular-nums">{f(r.value)}</TableCell></TableRow>)}</TableBody>
              </Table>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(300, items.length * 30)}>
              <BarChart data={items} layout="vertical" margin={{ left: 8, right: 80, top: 4, bottom: 4 }}>
                <CartesianGrid horizontal={false} stroke="#eee" />
                <XAxis type="number" tickFormatter={(v) => f(v as number)} fontSize={11} stroke="#888" />
                <YAxis type="category" dataKey="label" width={220} fontSize={11} stroke="#555" interval={0}
                  tickFormatter={(v: string) => (v.length > 32 ? v.slice(0, 31) + "…" : v)} />
                <Tooltip formatter={(v) => f(v as number)} labelFormatter={(l) => String(l)} cursor={{ fill: "rgba(45,106,79,0.06)" }} />
                <Bar dataKey="value" fill={GREEN} radius={[0, 2, 2, 0]}>
                  <LabelList dataKey="value" position="right" formatter={(v) => f(Number(v))} fontSize={10} fill="#555" />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
      </CardContent>
    </Card>
  );
}

// OPM-style "story" block: a question headline → a big data-driven hero number (auto-updates
// from the precomputed data) → a short evergreen explainer (no specific figures, so it never
// goes stale) → the interactive tool.
function Section({ q, intro, stat, children }: {
  q: string; intro?: string; stat?: { value: string; label: string }; children?: React.ReactNode;
}) {
  return (
    <section className="space-y-4 border-t pt-10">
      <h2 className="flex items-start gap-3 text-2xl font-bold tracking-tight">
        <span className="mt-2 inline-block h-3 w-3 shrink-0 rounded-full bg-primary/40" />
        {q}
      </h2>
      {stat && (
        <div className="border-l-4 border-primary pl-5">
          <div className="text-4xl font-bold tracking-tight text-primary tabular-nums sm:text-5xl">{stat.value}</div>
          <div className="mt-1 text-base text-muted-foreground">{stat.label}</div>
          <div className="mt-2 text-xs font-medium text-muted-foreground">
            Source: <a className="underline hover:text-foreground" href="https://files.usaspending.gov/award_data_archive/" target="_blank" rel="noreferrer">USAspending Award Data Archive</a>
          </div>
        </div>
      )}
      {intro && <p className="max-w-3xl text-muted-foreground">{intro}</p>}
      {children && <div className="space-y-4 pt-1">{children}</div>}
    </section>
  );
}

export function Explorer({ dataset }: { dataset: string }) {
  const [data, setData] = useState<Data | null>(null);
  const [agencyList, setAgencyList] = useState<Agency[]>([]);
  const [agency, setAgency] = useState(""); // agency slug; "" = all agencies

  useEffect(() => { setAgency(""); }, [dataset]);

  useEffect(() => {
    setData(null);
    const url = agency ? `/precomputed/${dataset}/agency/${agency}.json` : `/precomputed/${dataset}.json`;
    fetch(url).then((r) => r.json()).then((d: Data) => {
      setData(d);
      if (!agency && d.agencies) setAgencyList(d.agencies);
    }).catch(() => setData(null));
  }, [dataset, agency]);

  const kpi = data?.kpis["all"];
  const isC = dataset === "contracts";
  const noun = isC ? "contract" : "assistance";
  const dim = (k: string) => data?.dims[k];
  const agencyName = agencyList.find((a) => a.slug === agency)?.name || "";
  const setAgencyByName = (name: string) =>
    setAgency(name ? (agencyList.find((a) => a.name === name)?.slug || "") : "");

  return (
    <div className="space-y-10">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">
          Federal {isC ? "Contract" : "Assistance"} Spending{agencyName ? ` — ${agencyName}` : ""}
        </h1>
        <p className="mt-1 text-muted-foreground">
          Twenty years of federal {noun} awards (FY2007–2026), from the public USAspending Award Data Archive.
          Explore the views below, or <Link href="/table-builder" className="underline hover:text-foreground">build your own query</Link> for anything else.
        </p>
      </div>

      {agencyList.length > 0 && (
        <div className="max-w-md rounded border bg-muted/30 p-3">
          <Typeahead label="Agency" value={agencyName} options={agencyList.map((a) => a.name)} onChange={setAgencyByName} allLabel="All agencies" />
          {agencyName && <p className="mt-2 text-xs text-muted-foreground">Every figure and chart below is limited to {agencyName}.</p>}
        </div>
      )}

      {!data || !kpi ? (
        <div className="h-96 animate-pulse rounded-xl bg-muted/50" />
      ) : (
        <>
          <Section
            q={`How much does the U.S. government spend on ${isC ? "contracts" : "assistance"}?`}
            stat={{
              value: fmtUSD(kpi.obl),
              label: `in federal ${noun} obligations over FY2007–2026 — across ${fmtNum(kpi.txn)} awards, averaging ${kpi.txn ? fmtUSD(kpi.obl / kpi.txn) : "—"} each`,
            }}
            intro={isC
              ? "When the federal government buys goods and services — everything from fighter jets to office supplies and IT — it does so through contracts. Most federal prime contract awards are reported to USAspending.gov, though some classified and intelligence-community spending is excluded or withheld. These views summarize twenty years of it."
              : "Beyond buying goods and services, the government distributes money through grants, loans, direct payments, and other financial assistance — to states, organizations, and individuals. These views summarize twenty years of it."}
          />

          <Section
            q={`How has ${noun} spending changed over time?`}
            intro="Spending rises and falls with budgets, emergencies, and policy. Track total obligations by fiscal year, and narrow to a single agency or sub-agency to see how its spending has shifted."
          >
            <SpendingOverTime data={data} />
          </Section>

          {dim("recipient") && (
            <Section
              q="Who receives the money?"
              intro={`A relatively small number of large organizations account for much of federal ${noun} spending. These are the top recipients.`}
            >
              <Breakdown title="Top recipients" dim={dim("recipient")!} years={data.years} />
            </Section>
          )}

          <Section
            q={isC ? "What does it buy, and where?" : "What is it for, and where does it go?"}
            intro={isC
              ? "Contracts are categorized by industry (NAICS) and by the product or service bought (PSC), and tied to where the recipient is located."
              : "Assistance is tied to where recipients are located. Use the views below to see how it is distributed."}
          >
            {dim("naics") && <Breakdown title="Top industries (NAICS)" dim={dim("naics")!} years={data.years} />}
            {dim("psc") && <Breakdown title="Top products & services (PSC)" dim={dim("psc")!} years={data.years} />}
            {dim("state") && <Breakdown title="By recipient state" dim={dim("state")!} years={data.years} labelMap={STATE_NAMES} />}
          </Section>

          {(dim("competition") || dim("set_aside") || dim("business_size")) && (
            <Section
              q="How are awards made?"
              intro="Contracts can be competed openly or awarded without competition, and many are set aside for small or disadvantaged businesses."
            >
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
