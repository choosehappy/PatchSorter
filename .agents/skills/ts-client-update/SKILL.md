---
name: ts-client-update
description: Regenerate the hey-api/openapi-ts TypeScript client and refactor the React-TS app to consume it. Use this skill when the API has changed, the client needs regenerating, or TypeScript errors appear in service/query files. Client node root is patchsorter/client.
---

# ts-client-update

Regenerate the `hey-api/openapi-ts` client for `patchsorter/client`, then fix all React-TS call sites broken by the new schema.

## 1 — Orient

```bash
# Find config and output directory
cat patchsorter/client/openapi-ts.config.*

# Find all files importing from the generated client
grep -rl "from.*client\|from.*generated" patchsorter/client/src --include="*.ts" --include="*.tsx"
```

If `input` is a URL, confirm the backend is running first.

## 2 — Regenerate

```bash
cd patchsorter/client && npm run openapi-ts

# Review what changed
git diff --stat src/api_client
git diff src/api_client
```

Note every renamed type, removed field, and changed method signature.

## 3 — Fix breakages

```bash
npx tsc --noEmit 2>&1 | tee /tmp/tsc-errors.txt
```

Work through errors file by file:
- **Renamed type/method** → update import and usage
- **Removed/renamed field** → update all access expressions
- **New required field** → add at every call site
- **Response shape change** → update destructuring
- **Removed endpoint** → replace or remove the call

Never edit files inside the generated output directory (`src/api_client`) — put custom logic in wrappers outside it.

## 4 — Verify

```bash
npx tsc --noEmit   # must be clean
npm test -- --passWithNoTests
```

If tsc still errors, repeat step 3.

## 5 — Summarise

Report: input source, 0 tsc errors, files changed, breaking changes handled.