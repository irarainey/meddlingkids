<script setup lang="ts">
import { ref, watch, computed, onUnmounted } from 'vue'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import { js_beautify } from 'js-beautify'
import { stripQueryAndFragment } from '../utils'

hljs.registerLanguage('javascript', javascript)

/**
 * Fullscreen dialog for viewing syntax-highlighted JavaScript source.
 *
 * Fetches the script content via the server proxy to avoid CORS
 * restrictions, beautifies minified code with js-beautify, and
 * renders it with highlight.js colour coding.
 */
const props = defineProps<{
  /** Whether the dialog is visible */
  isOpen: boolean
  /** Full URL of the script to display */
  scriptUrl: string
  /** AI-generated description of the script's purpose */
  scriptDescription?: string
}>()

const emit = defineEmits<{
  /** Emitted when the dialog should close */
  close: []
}>()

const rawCode = ref('')
const isLoading = ref(false)
const errorMessage = ref('')
const isTruncated = ref(false)
const copied = ref(false)

/** URL without query string or fragment, matching the panel display. */
const shortUrl = computed(() => stripQueryAndFragment(props.scriptUrl))

/** Syntax-highlighted HTML produced by highlight.js. */
const highlightedHtml = computed(() => {
  if (!rawCode.value) return ''
  try {
    return hljs.highlight(rawCode.value, { language: 'javascript' }).value
  } catch {
    return rawCode.value
  }
})

/** Abort controller for in-flight fetch requests. */
let abortController: AbortController | null = null

/**
 * Fetch script content from the server proxy and apply
 * formatting + syntax highlighting.
 */
async function fetchScript(url: string): Promise<void> {
  if (!url) return

  // Cancel any in-flight request.
  abortController?.abort()
  abortController = new AbortController()

  isLoading.value = true
  errorMessage.value = ''
  rawCode.value = ''
  isTruncated.value = false
  copied.value = false

  try {
    const response = await fetch('/api/fetch-script', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
      signal: abortController.signal,
    })

    if (!response.ok) {
      errorMessage.value = `Server returned ${response.status}`
      return
    }

    const data: unknown = await response.json()

    if (typeof data !== 'object' || data === null) {
      errorMessage.value = 'Invalid response format'
      return
    }

    const result = data as Record<string, unknown>
    const content = typeof result.content === 'string' ? result.content : null
    const error = typeof result.error === 'string' ? result.error : undefined
    const truncated = typeof result.truncated === 'boolean' ? result.truncated : false

    if (error || !content) {
      errorMessage.value = error ?? 'No content returned'
      return
    }

    isTruncated.value = truncated

    // Beautify minified code for readability.
    const formatted = js_beautify(content, {
      indent_size: 2,
      indent_char: ' ',
      max_preserve_newlines: 2,
      preserve_newlines: true,
      end_with_newline: true,
    })

    rawCode.value = formatted
  } catch (err: unknown) {
    if (err instanceof Error && err.name === 'AbortError') return
    errorMessage.value = err instanceof Error ? err.message : 'Failed to fetch script'
  } finally {
    isLoading.value = false
  }
}

/** Copy the raw (beautified) code to the clipboard. */
async function copyToClipboard(): Promise<void> {
  if (!rawCode.value) return
  try {
    await navigator.clipboard.writeText(rawCode.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch {
    /* clipboard may be unavailable in some contexts */
  }
}

// Fetch content whenever the dialog opens with a new URL.
watch(
  () => props.isOpen,
  (open) => {
    if (open && props.scriptUrl) {
      fetchScript(props.scriptUrl)
    } else if (!open) {
      // Clean up when closing.
      abortController?.abort()
      rawCode.value = ''
      errorMessage.value = ''
    }
  },
)

onUnmounted(() => {
  abortController?.abort()
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="script-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="script-viewer-title"
      tabindex="-1"
      @click.self="emit('close')"
      @keydown.escape="emit('close')"
    >
      <div class="script-dialog">
        <!-- Header -->
        <header class="script-header">
          <div class="script-title-row">
            <h2 id="script-viewer-title" class="script-title">📜 Script Source</h2>
            <button class="dialog-close" aria-label="Close dialog" @click="emit('close')">&#10005;</button>
          </div>
          <div v-if="scriptDescription" class="script-description">{{ scriptDescription }}</div>
          <div class="script-url-row">
            <a :href="scriptUrl" target="_blank" class="script-url" :title="scriptUrl">{{ shortUrl }}</a>
            <button class="copy-btn" :class="{ copied }" @click="copyToClipboard" :disabled="!rawCode">
              {{ copied ? '✓ Copied' : '📋 Copy' }}
            </button>
          </div>
          <div v-if="isTruncated" class="truncation-notice">
            ⚠️ This script was truncated at 4096 KB. Click the link above to view the full script.
          </div>
        </header>

        <!-- Body -->
        <div class="script-body">
          <!-- Loading state -->
          <div v-if="isLoading" class="script-loading">
            <div class="loading-spinner" />
            <span>Fetching script…</span>
          </div>

          <!-- Error state -->
          <div v-else-if="errorMessage" class="script-error">
            <span class="error-icon">⚠️</span>
            <span>{{ errorMessage }}</span>
          </div>

          <!-- Code display -->
          <!-- eslint-disable-next-line vue/no-v-html -->
          <pre v-else-if="rawCode" class="script-pre"><code class="hljs language-javascript" v-html="highlightedHtml"></code></pre>

          <!-- Empty state -->
          <div v-else class="script-empty">No content to display</div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.script-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: stretch;
  justify-content: center;
  z-index: 1000;
  padding: 1.5rem;
}

.script-dialog {
  background: #1e2235;
  border: 1px solid #3d4663;
  border-radius: 12px;
  width: 100%;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

/* ── Header ─────────────────────────────────────────── */

.script-header {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid #2a2f45;
  flex-shrink: 0;
}

.script-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}

.script-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #e0e0e0;
  margin: 0;
}

.script-description {
  color: #9ca3af;
  font-size: 0.85rem;
  font-style: italic;
  line-height: 1.4;
  margin-bottom: 0.5rem;
}

.dialog-close {
  width: 32px;
  height: 32px;
  padding: 0;
  margin: 0;
  border: none;
  box-sizing: border-box;
  background: #2a2f45;
  color: #9ca3af;
  font-size: 1rem;
  line-height: 32px;
  text-align: center;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
}

.dialog-close:hover {
  background: #3d4663;
  color: #fff;
}

.script-url-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.script-url {
  color: #60a5fa;
  font-size: 0.85rem;
  text-decoration: none;
  word-break: break-all;
  flex: 1;
  min-width: 0;
}

.script-url:hover {
  text-decoration: underline;
}

.copy-btn {
  flex-shrink: 0;
  padding: 0.3rem 0.75rem;
  border: 1px solid #3d4663;
  border-radius: 6px;
  background: #1e2235;
  color: #9ca3af;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.copy-btn:hover:not(:disabled) {
  background: #2a2f45;
  color: #e0e0e0;
}

.copy-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.copy-btn.copied {
  color: #34d399;
  border-color: #34d399;
}

.truncation-notice {
  margin-top: 0.5rem;
  padding: 0.35rem 0.75rem;
  background: rgba(234, 179, 8, 0.1);
  border: 1px solid rgba(234, 179, 8, 0.3);
  border-radius: 6px;
  color: #eab308;
  font-size: 0.8rem;
}

/* ── Body ───────────────────────────────────────────── */

.script-body {
  flex: 1;
  overflow: auto;
  min-height: 0;
  background: #0b0e1a;
}

.script-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  height: 100%;
  min-height: 200px;
  color: #9ca3af;
  font-size: 0.95rem;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #2a2f45;
  border-top: 3px solid #60a5fa;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.script-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  height: 100%;
  min-height: 200px;
  color: #f87171;
  font-size: 0.95rem;
}

.script-pre {
  margin: 0;
  padding: 1rem 1.25rem;
  overflow: auto;
  font-family: 'Fira Code', 'JetBrains Mono', 'Cascadia Code', 'Consolas', 'Monaco', monospace;
  font-size: 0.8rem;
  line-height: 1.6;
  tab-size: 2;
  background: transparent;
}

.script-pre code {
  background: transparent;
  font-family: inherit;
}

.script-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 200px;
  color: #6b7280;
}
</style>

<!--
  highlight.js theme overrides — unscoped so they apply
  to the dynamically highlighted <code> element.
-->
<style>
.script-pre .hljs {
  background: transparent;
  color: #abb2bf;
}

.script-pre .hljs-keyword {
  color: #c678dd;
}

.script-pre .hljs-built_in {
  color: #e6c07b;
}

.script-pre .hljs-string,
.script-pre .hljs-regexp {
  color: #98c379;
}

.script-pre .hljs-number {
  color: #d19a66;
}

.script-pre .hljs-comment {
  color: #5c6370;
  font-style: italic;
}

.script-pre .hljs-function,
.script-pre .hljs-title {
  color: #61afef;
}

.script-pre .hljs-params {
  color: #abb2bf;
}

.script-pre .hljs-attr,
.script-pre .hljs-property {
  color: #e06c75;
}

.script-pre .hljs-literal {
  color: #56b6c2;
}

.script-pre .hljs-operator,
.script-pre .hljs-punctuation {
  color: #abb2bf;
}

.script-pre .hljs-meta {
  color: #61afef;
}

.script-pre .hljs-variable {
  color: #e06c75;
}
</style>
