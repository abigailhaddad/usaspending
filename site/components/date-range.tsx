"use client";

import type { DateRange } from "react-day-picker";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

const fmt = (d?: Date) =>
  d ? d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "";

export function DateRangePicker({
  value, onChange, placeholder = "Pick dates",
}: { value?: DateRange; onChange: (r?: DateRange) => void; placeholder?: string }) {
  const label = value?.from ? (value.to ? `${fmt(value.from)} – ${fmt(value.to)}` : fmt(value.from)) : placeholder;
  return (
    <Popover>
      <PopoverTrigger
        className="inline-flex w-[300px] items-center justify-start gap-2 rounded-lg border bg-background px-3 py-2 text-sm font-normal shadow-xs transition-colors hover:bg-muted data-[has-value=false]:text-muted-foreground"
        data-has-value={!!value?.from}
      >
        {label}
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="range" numberOfMonths={2} selected={value} onSelect={onChange}
          captionLayout="dropdown" startMonth={new Date(2007, 9)} endMonth={new Date(2026, 11)}
          autoFocus
        />
      </PopoverContent>
    </Popover>
  );
}
