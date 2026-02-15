/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional API base URL override (proxy handles routing by default) */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
