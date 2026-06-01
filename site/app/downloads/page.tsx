"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

type Index = {
  hf_dataset: string;
  reference: { name: string; desc: string; url: string }[];
  spending: { dataset: string; fiscal_year: string; files: number; rows: number; bytes: number; browse: string }[];
};

const fmtBytes = (b: number) => (b > 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${(b / 1e6).toFixed(1)} MB`);

export default function Downloads() {
  const [d, setD] = useState<Index | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    fetch("/api/downloads").then((r) => r.json()).then(setD).catch((e) => setErr(String(e)));
  }, []);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Bulk data downloads</h1>
        <p className="mt-1 text-muted-foreground">
          Public-domain federal contract &amp; assistance spending as clean Parquet. Download whole files,
          or build custom tables in the Table Builder.
        </p>
        {d && (
          <p className="mt-2 text-sm">
            Full dataset on HuggingFace:{" "}
            <a className="text-primary underline" href={d.hf_dataset} target="_blank" rel="noreferrer">
              {d.hf_dataset.replace("https://", "")}
            </a>
          </p>
        )}
      </div>

      {err && <p className="text-red-600">Error: {err}</p>}

      <Card>
        <CardHeader><CardTitle className="text-base">Reference &amp; data dictionary</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableBody>
              {d?.reference.map((r) => (
                <TableRow key={r.name}>
                  <TableCell>{r.desc}</TableCell>
                  <TableCell className="text-right">
                    <a className="text-primary underline" href={r.url}>download .parquet</a>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Spending files</CardTitle>
          <p className="text-sm text-muted-foreground">By dataset &amp; fiscal year, newest first. Each year is Parquet partitioned by agency.</p>
        </CardHeader>
        <CardContent>
          <div className="max-h-[600px] overflow-auto rounded-md border">
            <Table>
              <TableHeader className="sticky top-0 bg-muted">
                <TableRow>
                  <TableHead>Dataset</TableHead><TableHead>Fiscal year</TableHead>
                  <TableHead className="text-right">Files</TableHead>
                  <TableHead className="text-right">Rows</TableHead>
                  <TableHead className="text-right">Size</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {!d?.spending.length && (
                  <TableRow><TableCell colSpan={6} className="text-muted-foreground">Backfill in progress…</TableCell></TableRow>
                )}
                {d?.spending.map((s) => (
                  <TableRow key={s.dataset + s.fiscal_year}>
                    <TableCell className="capitalize">{s.dataset}</TableCell>
                    <TableCell>{s.fiscal_year}</TableCell>
                    <TableCell className="text-right tabular-nums">{s.files}</TableCell>
                    <TableCell className="text-right tabular-nums">{s.rows.toLocaleString()}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtBytes(s.bytes)}</TableCell>
                    <TableCell className="text-right">
                      <a className="text-primary underline" href={s.browse} target="_blank" rel="noreferrer">browse / download</a>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
