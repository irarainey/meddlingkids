/**
 * @fileoverview Server entry point - Express app setup and route configuration.
 * Sets up the Express server with CORS, JSON parsing, static file serving, and all API routes.
 */

import express from 'express'
import cors from 'cors'
import path from 'path'
import { fileURLToPath } from 'url'
import 'dotenv/config'

import { analyzeUrlStreamHandler } from './routes/index.js'

const app = express()
const PORT = process.env.PORT || 3001

// Get directory path for ES modules
const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// ============================================================================
// Middleware
// ============================================================================

app.use(cors())
app.use(express.json())

// ============================================================================
// API Routes
// ============================================================================

// URL analysis endpoint (SSE) - Analyzes tracking on a given URL
app.get('/api/open-browser-stream', analyzeUrlStreamHandler)

// ============================================================================
// Static File Serving (Production)
// ============================================================================

// In production, serve the built client files
if (process.env.NODE_ENV === 'production') {
  const distPath = path.resolve(__dirname, '../../dist')
  app.use(express.static(distPath))

  // SPA fallback - serve index.html for all non-API routes
  app.get('*', (_req, res) => {
    res.sendFile(path.join(distPath, 'index.html'))
  })
}

// ============================================================================
// Start Server
// ============================================================================

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`)
})
