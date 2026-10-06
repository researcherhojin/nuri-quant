"use client";

import { useId, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { DASHBOARD_NEXT as COPY } from "@/lib/strings";
import styles from "./dashboard.module.css";

/**
 * 설명·근거 팝업. `label` 이 접근성 이름이고 `icon` 은 장식(aria-hidden) — 이전엔 "읽는 법 ⓘ" 처럼
 * 문자 기호가 이름에 섞여 테스트와 스크린리더가 기호까지 읽었다 (#1658).
 */
export function DetailDialog({ label, icon, title, children, lazy = false }: {
  label: string;
  icon?: ReactNode;
  title: string;
  children: ReactNode;
  lazy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  const [opened, setOpened] = useState(false);

  return (
    <>
      <button type="button" className={styles.textButton} aria-haspopup="dialog" aria-controls={id} onClick={() => { setOpened(true); ref.current?.showModal(); }}>
        {label}
        {icon && <span aria-hidden="true" className={styles.labelIcon}>{icon}</span>}
      </button>
      <dialog id={id} ref={ref} className={styles.dialog} aria-label={title} onClose={() => setOpened(false)} onClick={(event) => {
        // 다이얼로그 내부 여백을 클릭해도 닫히지 않도록 실제 바깥 영역만 확인한다.
        if (event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();

        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) ref.current?.close();
      }}>
        <div className={styles.dialogHeading}>
          <h2>{title}</h2>
          <div>
            <kbd>{COPY.DIALOG.ESC}</kbd>
            <button type="button" aria-label={COPY.DIALOG.CLOSE} onClick={() => ref.current?.close()}><X size={18} /></button>
          </div>
        </div>
        {(!lazy || opened) && children}
      </dialog>
    </>
  );
}
