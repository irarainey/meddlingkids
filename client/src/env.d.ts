/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API base URL (empty in production, http://localhost:3001 in development) */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
