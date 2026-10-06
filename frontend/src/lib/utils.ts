import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 테이블 자신의 키인지 — 프로토타입 키("constructor" 등)는 false. 멤버 접근을 유지해야 할 때 쓴다. */
export function isKeyOf<T extends object>(table: T, key: string): key is Extract<keyof T, string> {
  return Object.hasOwn(table, key);
}

/**
 * 문자열 키 조회 — 테이블에 없는 키(프로토타입 키 포함)는 undefined.
 * 테이블은 `satisfies Record<string, T>` 로 선언해 리터럴 타입을 유지하고, 임의 문자열로 찾을 때만 이걸 쓴다.
 */
export function lookup<T>(table: Readonly<Record<string, T>>, key: string | null | undefined): T | undefined {
  return key != null && isKeyOf(table, key) ? table[key] : undefined;
}
