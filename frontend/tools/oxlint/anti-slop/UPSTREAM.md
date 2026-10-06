# anti-slop — vendored Oxlint plugin

- Source: https://github.com/dmmulroy/anti-slop (MIT)
- Copied from upstream commit `c44ef22` ("Merge pull request #36 from K-Mistele/contrib/effect-tag-match-rules") on 2026-10-06 via the upstream `install-anti-slop` skill script (`skills/install-anti-slop/scripts/install.mjs`), which copies `src/` without the rule test files.
- Installed at `frontend/tools/oxlint/anti-slop/`; registered in `frontend/.oxlintrc.json` as `jsPlugins` entry `anti-slop`; runs through `npm run lint` (`eslint && oxlint`). Pinned `oxlint` and `@oxlint/plugins` 1.87.0 (exact) in `frontend/package.json`.
- `LICENSE` is upstream's MIT notice, verbatim. `vendor/eslint-stylistic/` carries its own `LICENSE` and `UPSTREAM.md` (the padding-line rule that `require-readable-spacing` is built on).

## Deviations from upstream

- `effect/` (the opt-in Effect rules) removed — this repository has no `effect` dependency.
- `package.json` (`{"type": "module"}`) added so Node loads `index.ts` as ESM without the `MODULE_TYPELESS_PACKAGE_JSON` warning; the frontend's own `package.json` is CommonJS-typed.
- Rule severities are the repository's, not upstream's: see `frontend/CLAUDE.md` "Anti-slop (oxlint)" for the rules that are `off` and why (#1655).

To update, follow the upstream skill's `references/update.md` and record the new commit here.
