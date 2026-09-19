import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

/**
 * `next lint` was removed in Next 16, so linting runs through ESLint directly with the same
 * rule set `create-next-app` ships: React hooks, accessibility and the Next-specific checks.
 */
export default defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores(['.next/**', 'out/**', 'next-env.d.ts', 'tsconfig.tsbuildinfo']),
]);
