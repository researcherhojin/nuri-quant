import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import betterTailwind from "eslint-plugin-better-tailwindcss";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Auto-generated test coverage reports (gitignored, IDE 가 still 표시).
    "coverage/**",
  ]),
  // Tailwind canonical-class 게이트 (#1254). 이전엔 IDE(tailwindcss-intellisense) 만
  // 잡아서, 사용자가 경고를 붙여넣어야 발견되는 구조였다 — #1249 의 legacy important
  // 접두사(`!bg-muted`)가 그렇게 들어왔다.
  //
  // ⚠️ **`error` 다. `warn` 이 아니다.** 이슈는 warn 을 제안했지만, CI 의 Frontend Lint 는
  // `npm run lint` = 맨 `eslint` 라 `--max-warnings` 가 없고 워크플로 주석도 "errors-only
  // gate; warnings tolerated" 라고 명시한다. 즉 warn 으로 넣으면 **초록인 채 아무것도 막지
  // 않는 게이트**가 되고, 그건 이 레포가 반복해서 밟은 dead gate 다 (#910/#911 rc=127,
  // #953/#954 훅 exit 0). 규칙을 켜기 전에 기존 위반 187건을 0 으로 정규화했으므로
  // error 가 곧바로 성립한다.
  //
  // 켠 규칙은 **정본성(canonical)만** — 클래스 순서·줄바꿈 같은 미용 규칙은 뺐다.
  // 큰 기계적 diff 만 만들고 잘못된 클래스는 못 잡는다.
  {
    files: ["**/*.tsx", "**/*.ts"],
    plugins: { "better-tailwindcss": betterTailwind },
    settings: { "better-tailwindcss": { entryPoint: "src/app/globals.css" } },
    rules: {
      // #1249 의 실제 결함 축. 현재 위반 0 — 순수 예방용이다.
      "better-tailwindcss/enforce-consistent-important-position": "error",
      "better-tailwindcss/enforce-canonical-classes": "error",
      "better-tailwindcss/no-deprecated-classes": "error",
      "better-tailwindcss/no-conflicting-classes": "error",
      "better-tailwindcss/no-duplicate-classes": "error",
      // ❌ `no-unnecessary-whitespace` 는 **켜지 않는다.** 이 레포의 className 은 조각을
      // 이어붙이는 형태가 흔한데, 이 규칙은 조각을 **홀로** 보고 앞뒤 연결을 모른다.
      // 실측(#1254): `data-table.tsx` 의
      //   `}${col.hideOnMobile ? " hidden sm:table-cell" : ""}`
      // 에서 선행 조각(`text-left` 등)과 띄우는 **필수 공백**을 지워
      // cspell:ignore lefthidden — 규칙이 만든 깨진 클래스의 예시 그 자체
      // `text-lefthidden` 을 만들었다 — 클래스 둘이 동시에 죽는다. autofix 라 조용하다.
      // 규칙이 잡은 2건이 전부 이 오탐이었으므로 켤 이유가 없다.
    },
  },
  // Project-wide rule overrides — pragmatic baseline for a fast-moving dashboard.
  // `any` 광범위 사용 (dynamic API responses) + 의도된 unused params (signature compat) →
  // error→warn 으로 완화. PR 리뷰는 여전히 surface, blocking 만 해제.
  {
    rules: {
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-unused-vars": ["warn", { "argsIgnorePattern": "^_", "varsIgnorePattern": "^_" }],
      "@typescript-eslint/no-require-imports": "warn",
    },
  },
]);

export default eslintConfig;
