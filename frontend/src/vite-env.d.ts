/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCK?: string;
  readonly VITE_AGENT_ID?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
