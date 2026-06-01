export function fmtCell(v: unknown, col: string): string {
  if (v === null || v === undefined) return "";
  if (col.endsWith("Δ%")) return typeof v === "number" ? `${v > 0 ? "+" : ""}${v}%` : String(v);
  if (typeof v === "number") {
    if (col.includes("($)")) {
      const m = v / 1e6;
      return `${v < 0 ? "-$" : "$"}${Math.abs(m).toLocaleString(undefined, { maximumFractionDigits: 1 })}M`;
    }
    return v.toLocaleString();
  }
  return String(v);
}
export const B = (v: number) => v / 1e9;
