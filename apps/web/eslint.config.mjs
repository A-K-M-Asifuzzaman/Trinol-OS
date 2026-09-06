import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({
  baseDirectory: import.meta.dirname,
});

const eslintConfig = [
  // Global ignores must be their own config object with nothing but
  // `ignores` — mixed in with rules, flat config only applies it to files
  // matched by that object's own (nonexistent) `files`, not globally.
  {
    ignores: [".next/**", "next-env.d.ts", "lib/api/types.gen.ts"],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];

export default eslintConfig;
