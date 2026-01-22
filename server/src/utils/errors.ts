/**
 * @fileoverview Error handling utilities for consistent error message extraction.
 * Provides safe error handling across the application.
 */

/**
 * Safely extract an error message from an unknown error type.
 * Handles both Error instances and unknown thrown values.
 *
 * @param error - The caught error of unknown type
 * @returns The error message string, or 'Unknown error' for non-Error values
 *
 * @example
 * try {
 *   await riskyOperation()
 * } catch (error) {
 *   console.error(getErrorMessage(error))
 * }
 */
export function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unknown error'
}
