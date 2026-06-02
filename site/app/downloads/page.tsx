"use client";

import { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { DATASETS } from "@/lib/registry";

type ServeFile = { dataset: string; fiscal_year: string; rows: number; url: string };
type AgencyFile = { fiscal_year: string; rows: number; url: string };
type Agency = { code: string; name: string; files: AgencyFile[] };
type Index = {
  hf_dataset: string;
  serve: ServeFile[];
  agencies: Record<string, Agency[]>;
  reference: { name: string; desc: string; url: string }[];
};

const n = (x: number) => x.toLocaleString();

export default function Downloads() {
  const [d, setD] = useState<Index | null>(null);
  const [dataset, setDataset] = useState("contracts");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => { fetch("/api/downloads").then((r) => r.json()).then(setD).catch(() => {}); }, []);

  const serve = (d?.serve || []).filter((s) => s.dataset === dataset);
  const agencies = useMemo(
    () => (d?.agencies?.[dataset] || []).filter((a) => a.name.toLowerCase().includes(q.toLowerCase())),
    [d, dataset, q]);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Data downloads</h1>
        <p className="mt-1 text-muted-foreground">
          Public-domain federal contract &amp; assistance spending as Parquet — download whole years or single agencies
          right here, or build a filtered slice in the <a href="/" className="text-primary underline">Table Builder</a>.
        </p>
        {d && <p className="mt-2 text-sm">Full dataset on HuggingFace:{" "}
          <a className="text-primary underline" href={d.hf_dataset} target="_blank" rel="noreferrer">{d.hf_dataset.replace("https://", "")}</a></p>}
      </div>

      <div className="flex items-center gap-3">
        <span className="text-sm font-medium">Dataset</span>
        <Select value={dataset} onValueChange={(v) => { setDataset(v ?? ""); setOpen(null); }}>
          <SelectTrigger className="w-56"><SelectValue /></SelectTrigger>
          <SelectContent>{DATASETS.map((x) => <SelectItem key={x.value} value={x.value}>{x.label}</SelectItem>)}</SelectContent>
        </Select>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Whole fiscal years</CardTitle>
          <p className="text-sm text-muted-foreground">One file per year (all agencies), newest first.</p>
        </CardHeader>
        <CardContent>
          <div className="max-h-[420px] overflow-auto rounded-md border">
            <Table>
              <TableHeader className="sticky top-0 bg-muted">
                <TableRow><TableHead>Fiscal year</TableHead><TableHead className="text-right">Rows</TableHead><TableHead></TableHead></TableRow>
              </TableHeader>
              <TableBody>
                {serve.length === 0 && <TableRow><TableCell colSpan={3} className="text-muted-foreground">building…</TableCell></TableRow>}
                {serve.map((s) => (
                  <TableRow key={s.fiscal_year}>
                    <TableCell>FY{s.fiscal_year}</TableCell>
                    <TableCell className="text-right tabular-nums">{n(s.rows)}</TableCell>
                    <TableCell className="text-right"><a className="text-primary underline" href={s.url}>download .parquet</a></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">By agency</CardTitle>
          <p className="text-sm text-muted-foreground">Search an agency, then download its file for any year.</p>
        </CardHeader>
        <CardContent className="space-y-2">
          <Input placeholder="Search agencies…" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-sm" />
          <div className="max-h-[460px] overflow-auto rounded-md border">
            {agencies.map((a) => (
              <div key={a.code} className="border-b last:border-0">
                <button className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-muted"
                  onClick={() => setOpen(open === a.code ? null : a.code)}>
                  <span>{a.name} <span className="text-muted-foreground">({a.code})</span></span>
                  <span className="text-muted-foreground">{a.files.length} years {open === a.code ? "▾" : "▸"}</span>
                </button>
                {open === a.code && (
                  <div className="bg-muted/40 px-3 py-2">
                    <Table>
                      <TableBody>
                        {a.files.map((f) => (
                          <TableRow key={f.fiscal_year}>
                            <TableCell className="py-1">FY{f.fiscal_year}</TableCell>
                            <TableCell className="py-1 text-right tabular-nums">{n(f.rows)}</TableCell>
                            <TableCell className="py-1 text-right"><a className="text-primary underline" href={f.url}>download .parquet</a></TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </div>
            ))}
            {d && agencies.length === 0 && <p className="px-3 py-2 text-sm text-muted-foreground">no agencies match</p>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Reference &amp; data dictionary</CardTitle></CardHeader>
        <CardContent>
          <Table><TableBody>
            {d?.reference.map((r) => (
              <TableRow key={r.name}>
                <TableCell>{r.desc}</TableCell>
                <TableCell className="text-right"><a className="text-primary underline" href={r.url}>download .parquet</a></TableCell>
              </TableRow>
            ))}
          </TableBody></Table>
        </CardContent>
      </Card>
    </div>
  );
}
