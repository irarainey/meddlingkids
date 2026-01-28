/**
 * @fileoverview Formatting utility functions for display.
 */

/**
 * Format a cookie expiry timestamp for display.
 *
 * @param expires - Unix timestamp in seconds, or -1 for session cookies
 * @returns Human-readable expiry string
 */
export function formatExpiry(expires: number): string {
  if (expires === -1) return 'Session'
  const date = new Date(expires * 1000)
  return date.toLocaleDateString() + ' ' + date.toLocaleTimeString()
}

/**
 * Truncate a string value for display.
 *
 * @param value - The string to truncate
 * @param maxLength - Maximum length before truncation (default: 50)
 * @returns Truncated string with ellipsis if needed
 */
export function truncateValue(value: string, maxLength = 50): string {
  if (value.length <= maxLength) return value
  return value.substring(0, maxLength) + '...'
}

/**
 * Get an emoji icon for a network resource type.
 *
 * @param type - The resource type (script, xhr, image, etc.)
 * @returns Emoji representing the resource type
 */
export function getResourceTypeIcon(type: string): string {
  const icons: Record<string, string> = {
    script: '📜',
    xhr: '🔄',
    fetch: '🔄',
    image: '🖼️',
    stylesheet: '🎨',
    font: '🔤',
    document: '📄',
    other: '📦',
  }
  return icons[type] || '📦'
}

/**
 * Convert simple markdown to HTML for display.
 * Handles headers, bold, italic, code blocks, lists, and line breaks.
 *
 * @param text - Markdown text to convert
 * @returns HTML string
 */
export function formatMarkdown(text: string): string {
  // Normalize whitespace: collapse multiple blank lines between list items
  const normalized = text
    .replace(/^(- .+)\n\n+(- )/gm, '$1\n$2')
    .replace(/\n{3,}/g, '\n\n')

  const html = normalized
    // Escape HTML
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // Headers
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Code blocks
    .replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
    // Inline code
    .replace(/`(.+?)`/g, '<code>$1</code>')
    // Lists
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>')
    // Line breaks
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>')

  return `<p>${html}</p>`
}
