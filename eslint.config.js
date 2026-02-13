import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'

export default tseslint.config(
  // Global ignores
  {
    ignores: ['dist/**', '**/dist/**', 'node_modules/**', 'server/**', '*.config.js', '*.config.ts'],
  },

  // Base JavaScript rules
  js.configs.recommended,

  // TypeScript rules
  ...tseslint.configs.recommended,

  // Vue rules - use essential instead of recommended for less strict formatting
  ...pluginVue.configs['flat/essential'],

  // Configure Vue parser for TypeScript
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
      },
      globals: {
        // Browser globals for Vue components
        Event: 'readonly',
        EventSource: 'readonly',
        HTMLInputElement: 'readonly',
        HTMLElement: 'readonly',
        MouseEvent: 'readonly',
        KeyboardEvent: 'readonly',
        Document: 'readonly',
        Window: 'readonly',
        URLSearchParams: 'readonly',
        window: 'readonly',
        document: 'readonly',
        console: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        navigator: 'readonly',
        fetch: 'readonly',
        URL: 'readonly',
        AbortController: 'readonly',
      },
    },
  },

  // Client-side rules
  {
    files: ['client/**/*.ts', 'client/**/*.vue'],
    rules: {
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'warn',
      'vue/multi-word-component-names': 'off',
      'vue/no-v-html': 'off',
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },


)
