import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["src/components/VasoolConsole.tsx"],
    rules: {
      // Vasool's console intentionally owns its initial/polling data sync in
      // one client component. The load callback updates UI state and is
      // invoked asynchronously by the browser effect; the rule is overly
      // conservative here and would otherwise reject the polling bootstrap.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
