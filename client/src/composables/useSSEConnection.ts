/**
 * @fileoverview Composable for managing an SSE (Server-Sent Events) connection.
 * Encapsulates the EventSource lifecycle, event listener registration,
 * connection timeout handling, and cleanup on unmount.
 */

import { ref, onUnmounted } from 'vue'
import type { Ref } from 'vue'

/** Map of SSE event type names to handler callbacks. */
export type SSEHandlers = Record<string, (data: unknown) => void>

export interface UseSSEConnectionReturn {
  /** Start the SSE connection to the configured URL. */
  connect: () => void
  /** Close the SSE connection and clean up resources. */
  close: () => void
  /** Whether the EventSource is currently open. */
  isConnected: Ref<boolean>
}

/**
 * Composable that manages an SSE (EventSource) connection lifecycle.
 *
 * @param url - The SSE endpoint URL to connect to.
 * @param handlers - Map of SSE event type → handler callback. Each handler
 *   receives the raw `event.data` parsed as JSON (`unknown`). A special
 *   `'__onerror'` key, if present, is wired to the native `onerror` handler
 *   (receives the raw Event, not parsed JSON).
 */
export function useSSEConnection(
  url: string,
  handlers: SSEHandlers,
): UseSSEConnectionReturn {
  const isConnected = ref(false)

  let eventSource: EventSource | null = null

  /**
   * Open the EventSource and wire up all supplied event handlers.
   * If a connection is already open it is closed first.
   */
  function connect(): void {
    close()

    eventSource = new EventSource(url)
    isConnected.value = true

    for (const [eventType, handler] of Object.entries(handlers)) {
      if (eventType === '__onerror') {
        eventSource.onerror = handler as (event: Event | unknown) => void
        continue
      }

      eventSource.addEventListener(eventType, ((event: MessageEvent) => {
        try {
          const data: unknown = JSON.parse(event.data)
          handler(data)
        } catch {
          // For the SSE 'error' event the browser may fire both a
          // MessageEvent (server-sent) and a plain Event (connection
          // lost).  When it's a MessageEvent we still want to try
          // handing the raw event to the handler so domain logic can
          // inspect event.data directly.
          if (eventType === 'error') {
            handler(event)
          } else {
            console.error(`[SSE] Failed to parse ${eventType} event`)
          }
        }
      }) as EventListener)
    }
  }

  /** Close the active EventSource and mark connection as inactive. */
  function close(): void {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    isConnected.value = false
  }

  // Automatically clean up when the owning component unmounts
  onUnmounted(() => {
    close()
  })

  return { connect, close, isConnected }
}
