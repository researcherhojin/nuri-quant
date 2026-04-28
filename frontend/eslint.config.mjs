import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

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
