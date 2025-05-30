import react from "eslint-plugin-react";
import ts from "eslint-plugin-typescript";
import tsParser from "@typescript-eslint/parser";

export default [
  {
    files: ["**/*.ts", "**/*.tsx"],
    ignores: ["dist/**/*", "node_modules/**/*"],
    languageOptions: {
      parser: tsParser,
      ecmaVersion: 2021,
      sourceType: "module",
    },
    plugins: {
      react,
      ts,
    },
    rules: {
      "semi": ["error", "always"],
      "react/react-in-jsx-scope": "off",
      "no-unused-vars": "warn",
    },
    settings: {
      react: {
        version: "detect",
      },
    },
  },
  {
    files: ["**/*.js", "**/*.jsx"],
    languageOptions: {
      ecmaVersion: 2021,
      sourceType: "module",
    },
    plugins: {
      react,
    },
    rules: {
      "semi": ["error", "always"],
      "react/react-in-jsx-scope": "off",
      "no-unused-vars": "warn",
    },
    settings: {
      react: {
        version: "detect",
      },
    },
  },
];
