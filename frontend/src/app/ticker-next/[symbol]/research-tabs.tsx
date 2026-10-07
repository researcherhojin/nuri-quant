"use client";

import { useId, type ReactNode, type KeyboardEvent } from "react";
import { useSearchParams } from "next/navigation";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import styles from "./ticker.module.css";

const keys = ["brief", "evidence", "research", "history"];

export function ResearchTabs({ brief, evidence, research, history }: { brief: ReactNode; evidence: ReactNode; research: ReactNode; history: ReactNode }) {
  const id = useId();
  const params = useSearchParams();
  const selected = Math.max(0, keys.indexOf(params.get("tab") || "brief"));
  const labels = [T.BRIEF, T.EVIDENCE, T.RESEARCH, T.HISTORY];
  const panels = [brief, evidence, research, history];

  function select(index: number) {
    if (index === selected) return;

    const url = new URL(window.location.href);

    url.searchParams.set("tab", keys[index]);
    url.hash = "";
    window.history.pushState(null, "", url);
  }

  function navigate(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;

    if (event.key === "ArrowRight") next = (index + 1) % labels.length;
    else if (event.key === "ArrowLeft") next = (index + labels.length - 1) % labels.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = labels.length - 1;
    else return;

    event.preventDefault();
    select(next);
    document.getElementById(`${id}-tab-${next}`)?.focus();
  }

  return (
    <div>
      <div className={styles.tabs} role="tablist" aria-label={T.DETAIL_TABS}>
        {labels.map((label, index) => <button key={label} type="button" role="tab" id={`${id}-tab-${index}`} aria-controls={`${id}-panel-${index}`} aria-selected={selected === index} tabIndex={selected === index ? 0 : -1} onClick={() => select(index)} onKeyDown={event => navigate(event, index)}>{label}</button>)}
      </div>
      {panels.map((panel, index) => <div key={labels[index]} role="tabpanel" id={`${id}-panel-${index}`} aria-labelledby={`${id}-tab-${index}`} hidden={selected !== index} tabIndex={0}>{selected === index && panel}</div>)}
    </div>
  );
}
