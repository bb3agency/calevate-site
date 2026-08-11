import { dirname } from "path";
import { fileURLToPath } from "url";

import { FlatCompat } from "@eslint/eslintrc";

/**
 * `eslint-config-next@15` still ships eslintrc-shaped configs (`module.exports =
 * { extends: [...] }`), not flat-config arrays. Importing them directly into a flat
 * config throws "nextVitals is not iterable" — which it had been doing, so `pnpm lint`
 * has never actually linted anything. FlatCompat is the bridge Next's own scaffold
 * uses; drop it when eslint-config-next ships flat config natively.
 */
const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const eslintConfig = [
  { ignores: [".next/**", "out/**", "build/**", "next-env.d.ts"] },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];

export default eslintConfig;
