"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { DATASETS } from "@/lib/registry";

const GREEN = "#2d6a4f";
type Row = { label: string; value: number };

async function agg(dataset: string, dim: string, top?: number): Promise<Row[]> {
  const u = `/api/table?dataset=${dataset}&rows=${dim}&metric=obligations` + (top ? `&top=${top}` : "");
  const j = await (await fetch(u)).json();
  if (!j.tables?.[0]) return [];
  return j.tables[0].data
    .filter((r: unknown[]) => r[0] != null && r[1] != null)
    .map((r: [string, number]) => ({ label: String(r[0]), value: r[1] / 1e9 }));
}

const money = (v: number) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}B`;

function Panel({
  title, dataset, dim, top, horizontal = true, builderDim,
}: { title: string; dataset: string; dim: string; top?: number; horizontal?: boolean; builderDim?: string }) {
  const [data, setData] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  useEffect(() => {
    let on = true; setLoading(true);
    agg(dataset, dim, top).then((d) => { if (on) { setData(d); setLoading(false); } });
    return () => { on = false; };
  }, [dataset, dim, top]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
        {builderDim && (
          <Button variant="ghost" size="sm"
            onClick={() => router.push(`/?dataset=${dataset}&rows=${builderDim}&metric=obligations`)}>
            open in builder →
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex h-[320px] items-center justify-center text-sm text-muted-foreground">loading…</div>
        ) : horizontal ? (
          <ResponsiveContainer width="100%" height={Math.max(320, data.length * 26)}>
            <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
              <CartesianGrid horizontal={false} stroke="#eee" />
              <XAxis type="number" tickFormatter={(v) => `$${v}B`} fontSize={12} stroke="#888" />
              <YAxis type="category" dataKey="label" width={220} fontSize={12} stroke="#555" interval={0} />
              <Tooltip formatter={(v: number) => money(v)} cursor={{ fill: "rgba(45,106,79,0.06)" }} />
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
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Visualizations</h1>
          <p className="mt-1 text-muted-foreground">Where federal contract &amp; assistance money goes, at a glance.</p>
        </div>
        <Select value={dataset} onValueChange={setDataset}>
          <SelectTrigger className="w-56"><SelectValue /></SelectTrigger>
          <SelectContent>{DATASETS.map((d) => <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>)}</SelectContent>
        </Select>
      </div>

      <Panel title="Obligations by fiscal year" dataset={dataset} dim="fiscal_year" horizontal={false} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Top awarding agencies" dataset={dataset} dim="awarding_agency" top={15} builderDim="awarding_agency" />
        <Panel title="Top recipients" dataset={dataset} dim="recipient" top={15} builderDim="recipient" />
        <Panel title="Top states" dataset={dataset} dim="state" top={15} builderDim="state" />
        <Panel title="Competition" dataset={dataset} dim="extent_competed" builderDim="extent_competed" />
        <Panel title="Top products & services" dataset={dataset} dim="psc_desc" top={15} builderDim="psc_desc" />
        <Panel title="Top industries (NAICS)" dataset={dataset} dim="naics_desc" top={15} builderDim="naics_desc" />
      </div>
    </div>
  );
}
