/**
 * @fileoverview Server entry point - Express app setup and route configuration.
 * Sets up the Express server with CORS, JSON parsing, and all API routes.
 */

import express from 'express'
import cors from 'cors'
import 'dotenv/config'

import { analyzeUrlStreamHandler } from './routes/index.js'

const app = express()
const PORT = process.env.PORT || 3001

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
// Start Server
// ============================================================================

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`)
})
