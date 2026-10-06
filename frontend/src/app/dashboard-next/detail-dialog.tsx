"use client";

import { useId, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import styles from "./dashboard.module.css";

export function DetailDialog({ label, title, children, lazy = false }: { label: string; title: string; children: ReactNode; lazy?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  const [opened, setOpened] = useState(false);
  return (
    <>
      <button type="button" className={styles.textButton} aria-haspopup="dialog" aria-controls={id} onClick={() => { setOpened(true); ref.current?.showModal(); }}>{label}</button>
      <dialog id={id} ref={ref} className={styles.dialog} aria-label={title} onClose={() => setOpened(false)} onClick={(event) => {
        // 다이얼로그 내부 여백을 클릭해도 닫히지 않도록 실제 바깥 영역만 확인한다.
        if (event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) ref.current?.close();
      }}>
        <div className={styles.dialogHeading}><h2>{title}</h2><div><kbd>ESC</kbd><button type="button" aria-label="닫기" onClick={() => ref.current?.close()}><X size={18} /></button></div></div>
        {(!lazy || opened) && children}
      </dialog>
    </>
  );
}
