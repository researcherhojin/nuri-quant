/**
 * EventsStrip (#1204 U2a) — 다가오는 실적 이벤트 스트립. page.tsx 에서 추출, 동작 불변.
 */
import { CollapsibleStrip } from "@/components/ui/collapsible-strip";
import { STRIP, COMMON } from "@/lib/strings";
import { fmtEventDate, eventDday } from "./helpers";

export interface StripEvent { date: string; description?: string; ticker: string | null }

export function EventsStrip({ events }: { events: StripEvent[] }) {
  if (events.length === 0) return null;
  return (
    <CollapsibleStrip
      id="events"
      title={STRIP.EVENTS_TITLE}
      icon="📅"
      count={events.length}
      emptyText={STRIP.EVENTS_EMPTY}
    >
      <div className="flex items-start gap-2 px-2 py-1 rounded bg-zinc-900/40 border border-zinc-800/60 pr-6">
        <span className="text-[10px] text-zinc-400 font-semibold shrink-0">{STRIP.EVENTS_PREFIX} {events.length}{COMMON.COUNT_SUFFIX}</span>
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 flex-1 min-w-0">
          {events.map((ev, i) => {
            const dday = eventDday(ev.date);
            return (
              <span key={`${ev.date}-${i}`} className="text-[10px] text-zinc-400 truncate">
                <span className="text-zinc-600 tabular-nums">{fmtEventDate(ev.date)}</span>{" "}
                {ev.description || ev.ticker || STRIP.EVENTS_FALLBACK}
                {dday && <span className="text-zinc-600 ml-1">({dday})</span>}
              </span>
            );
          })}
        </div>
      </div>
    </CollapsibleStrip>
  );
}
