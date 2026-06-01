"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { DateRange } from "react-day-picker";
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { DateRangePicker } from "@/components/date-range";
import { MultiSelect } from "@/components/multi-select";
import { DATASETS } from "@/lib/registry";

const GREEN = "#2d6a4f";
type Row = { label: string; value: number };

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

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

const money = (v: number) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}B`;

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
        {loading ? (
          <div className="flex h-[320px] items-center justify-center text-sm text-muted-foreground">loading…</div>
        ) : data.length === 0 ? (
          <div className="flex h-[320px] items-center justify-center text-sm text-muted-foreground">no data for these filters</div>
        ) : horizontal ? (
          <ResponsiveContainer width="100%" height={Math.max(320, data.length * 26)}>
            <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
              <CartesianGrid horizontal={false} stroke="#eee" />
              <XAxis type="number" tickFormatter={(v) => `$${v}B`} fontSize={12} stroke="#888" />
              <YAxis type="category" dataKey="label" width={240} fontSize={12} stroke="#555" interval={0}
                tickFormatter={(v: string) => (v.length > 38 ? v.slice(0, 37) + "…" : v)} />
              <Tooltip formatter={(v: number) => money(v)} labelFormatter={(l) => String(l)}
                cursor={{ fill: "rgba(45,106,79,0.06)" }} />
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
              <Bar dataKey="value" fill={GREEN} radius={[3, 3, 0, 0]}>
                {data.map((_, i) => <Cell key={i} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

export default function Visualizations() {
  const [dataset, setDataset] = useState("contracts");
  const [range, setRange] = useState<DateRange | undefined>();
  const [agency, setAgency] = useState<string[]>([]);
  const [state, setState] = useState<string[]>([]);
  const [awardType, setAwardType] = useState<string[]>([]);

  const p = new URLSearchParams();
  if (range?.from && range?.to) p.set("periodA", `${iso(range.from)}..${iso(range.to)}`);
  if (agency.length) p.set("filter_awarding_agency", agency.join("|"));
  if (state.length) p.set("filter_state", state.join("|"));
  if (awardType.length) p.set("filter_award_type", awardType.join("|"));
  const qs = p.toString();

  const clearAll = () => { setRange(undefined); setAgency([]); setState([]); setAwardType([]); };
  const active = (range?.from ? 1 : 0) + agency.length + state.length + awardType.length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Visualizations</h1>
        <p className="mt-1 text-muted-foreground">Where federal contract &amp; assistance money goes. Use the filters to focus every chart at once.</p>
      </div>

      {/* shared filter bar — applies to all charts */}
      <Card className="sticky top-[57px] z-10">
        <CardContent className="flex flex-wrap items-center gap-2 py-3">
          <Select value={dataset} onValueChange={setDataset}>
            <SelectTrigger className="h-9 w-44"><SelectValue /></SelectTrigger>
            <SelectContent>{DATASETS.map((d) => <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>)}</SelectContent>
          </Select>
          <DateRangePicker value={range} onChange={setRange} placeholder="All dates" />
          <MultiSelect field="awarding_agency" dataset={dataset} label="Agency" value={agency} onChange={setAgency} />
          <MultiSelect field="state" dataset={dataset} label="State" value={state} onChange={setState} />
          <MultiSelect field="award_type" dataset={dataset} label="Award type" value={awardType} onChange={setAwardType} />
          {active > 0 && <Button variant="ghost" size="sm" onClick={clearAll}>Clear filters ({active})</Button>}
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
    </div>
  );
}
