/**
 * @fileoverview Barrel export for route handlers.
 * Re-exports all Express route handlers for the API.
 *
 * Available handlers:
 * - analyzeUrlStreamHandler: SSE streaming for URL tracking analysis
 */

export { analyzeUrlStreamHandler } from './analyze-stream.js'
