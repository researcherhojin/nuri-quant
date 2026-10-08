"use client";

import { useCallback, useId, useSyncExternalStore, type ReactNode, type KeyboardEvent } from "react";
import { useSearchParams } from "next/navigation";
import { TICKER_PREVIEW as T } from "@/lib/strings";
import styles from "./ticker.module.css";

const keys = ["brief", "evidence", "research", "history"];
// pushState 는 popstate 를 내지 않으므로 탭 선택 뒤 이 이벤트로 구독자를 깨운다.
const TAB_EVENT = "nuri:ticker-tab";

// 탭은 실제 브라우저 URL 을 따른다. useSearchParams 만 보면 라우터가 popstate 를 놓쳤을 때(CI 에서
// 뒤로 가기 후 15 초 동안 옛 탭에 머물렀다, #1750) 화면이 URL 과 어긋난다.
function subscribe(onChange: () => void) {
  window.addEventListener("popstate", onChange);
  window.addEventListener(TAB_EVENT, onChange);

  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(TAB_EVENT, onChange);
  };
}

const browserTab = () => new URLSearchParams(window.location.search).get("tab");

export function ResearchTabs({ brief, evidence, research, history }: { brief: ReactNode; evidence: ReactNode; research: ReactNode; history: ReactNode }) {
  const id = useId();
  const params = useSearchParams();
  const serverTab = useCallback(() => params.get("tab"), [params]);
  const tab = useSyncExternalStore(subscribe, browserTab, serverTab);
  const selected = Math.max(0, keys.indexOf(tab || "brief"));
  const labels = [T.BRIEF, T.EVIDENCE, T.RESEARCH, T.HISTORY];
  const panels = [brief, evidence, research, history];

  function select(index: number) {
    if (index === selected) return;

    const url = new URL(window.location.href);

    url.searchParams.set("tab", keys[index]);
    url.hash = "";
    window.history.pushState(null, "", url);
    window.dispatchEvent(new Event(TAB_EVENT));
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
