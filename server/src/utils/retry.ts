/**
 * @fileoverview Retry utility with exponential backoff for handling transient failures.
 * Particularly useful for handling rate limits (429) from OpenAI APIs.
 */

import { createLogger } from './logger.js'

const log = createLogger('Retry')

/** Options for configuring retry behavior */
export interface RetryOptions {
  /** Maximum number of retry attempts (default: 3) */
  maxRetries?: number
  /** Initial delay in milliseconds before first retry (default: 1000) */
  initialDelayMs?: number
  /** Maximum delay in milliseconds between retries (default: 30000) */
  maxDelayMs?: number
  /** Multiplier for exponential backoff (default: 2) */
  backoffMultiplier?: number
  /** Optional context string for logging */
  context?: string
}

/** Default retry configuration */
const DEFAULT_OPTIONS: Required<Omit<RetryOptions, 'context'>> = {
  maxRetries: 3,
  initialDelayMs: 1000,
  maxDelayMs: 30000,
  backoffMultiplier: 2,
}

/**
 * Check if an error is a rate limit error (429).
 */
function isRateLimitError(error: unknown): boolean {
  if (error && typeof error === 'object') {
    // OpenAI SDK error format
    if ('status' in error && error.status === 429) {
      return true
    }
    // Check for status code in nested error
    if ('error' in error && typeof error.error === 'object' && error.error !== null) {
      const innerError = error.error as Record<string, unknown>
      if (innerError.code === '429' || innerError.status === 429) {
        return true
      }
    }
    // Check message for rate limit indication
    if ('message' in error && typeof error.message === 'string') {
      return error.message.includes('429') || error.message.toLowerCase().includes('rate limit')
    }
  }
  return false
}

/**
 * Check if an error is retryable (rate limits, server errors, network issues).
 */
function isRetryableError(error: unknown): boolean {
  if (isRateLimitError(error)) {
    return true
  }
  
  if (error && typeof error === 'object') {
    // Server errors (5xx) are typically retryable
    if ('status' in error && typeof error.status === 'number') {
      return error.status >= 500 && error.status < 600
    }
    // Network errors
    if ('code' in error) {
      const code = (error as { code: string }).code
      return ['ECONNRESET', 'ETIMEDOUT', 'ECONNREFUSED', 'EPIPE'].includes(code)
    }
  }
  return false
}

/**
 * Extract retry-after delay from error headers if available.
 */
function getRetryAfterMs(error: unknown): number | null {
  if (error && typeof error === 'object' && 'headers' in error) {
    const headers = (error as { headers: Record<string, string> }).headers
    if (headers && typeof headers === 'object') {
      // Check for retry-after header (in seconds)
      const retryAfter = headers['retry-after'] || headers['Retry-After']
      if (retryAfter) {
        const seconds = parseInt(retryAfter, 10)
        if (!isNaN(seconds)) {
          return seconds * 1000
        }
      }
      // Check for x-ratelimit-reset-requests or similar headers
      const resetMs = headers['x-ratelimit-reset-requests'] || headers['x-ratelimit-reset-tokens']
      if (resetMs) {
        // This is often in a format like "1s" or "200ms"
        const match = resetMs.match(/(\d+)(ms|s)?/)
        if (match) {
          const value = parseInt(match[1], 10)
          const unit = match[2] || 's'
          return unit === 'ms' ? value : value * 1000
        }
      }
    }
  }
  return null
}

/**
 * Sleep for a specified duration.
 */
function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

/**
 * Execute an async function with automatic retry on transient failures.
 * Uses exponential backoff with optional jitter for rate limit handling.
 *
 * @param fn - The async function to execute
 * @param options - Retry configuration options
 * @returns The result of the function if successful
 * @throws The last error if all retries are exhausted
 *
 * @example
 * const result = await withRetry(
 *   () => client.chat.completions.create({ ... }),
 *   { maxRetries: 3, context: 'Main analysis' }
 * )
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  options: RetryOptions = {}
): Promise<T> {
  const config = { ...DEFAULT_OPTIONS, ...options }
  const { maxRetries, initialDelayMs, maxDelayMs, backoffMultiplier, context } = config

  let lastError: unknown
  let delay = initialDelayMs

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn()
    } catch (error) {
      lastError = error

      // Don't retry if it's not a retryable error
      if (!isRetryableError(error)) {
        throw error
      }

      // Don't retry if we've exhausted all attempts
      if (attempt >= maxRetries) {
        log.warn('All retry attempts exhausted', {
          context,
          attempts: attempt + 1,
          error: error instanceof Error ? error.message : String(error),
        })
        throw error
      }

      // Calculate delay with exponential backoff
      const retryAfterMs = getRetryAfterMs(error)
      const actualDelay = retryAfterMs ?? delay

      // Add jitter (±20%) to prevent thundering herd
      const jitter = actualDelay * 0.2 * (Math.random() * 2 - 1)
      const delayWithJitter = Math.min(Math.round(actualDelay + jitter), maxDelayMs)

      log.warn('Retrying after transient error', {
        context,
        attempt: attempt + 1,
        maxRetries,
        delayMs: delayWithJitter,
        isRateLimit: isRateLimitError(error),
        error: error instanceof Error ? error.message.slice(0, 100) : String(error).slice(0, 100),
      })

      await sleep(delayWithJitter)

      // Increase delay for next attempt
      delay = Math.min(delay * backoffMultiplier, maxDelayMs)
    }
  }

  throw lastError
}
