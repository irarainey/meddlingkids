/// <reference types="vite/client" />

/** Injected at build time by Vite from package.json */
declare const __APP_VERSION__: string

interface ImportMetaEnv {
  /** Optional API base URL override (proxy handles routing by default) */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
