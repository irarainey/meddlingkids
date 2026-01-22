// Server entry point - Express app setup and route configuration

import express from 'express'
import cors from 'cors'
import 'dotenv/config'

import { closeBrowser } from './services/browser.js'
import {
  openBrowserStreamHandler,
  clickHandler,
  clickSelectorHandler,
  typeHandler,
  stateHandler,
  cookiesHandler,
  scriptsHandler,
  analyzeHandler,
} from './routes/index.js'

const app = express()
const PORT = process.env.PORT || 3001

// Middleware
app.use(cors())
app.use(express.json({ limit: '50mb' }))

// Browser streaming endpoint (SSE)
app.get('/api/open-browser-stream', openBrowserStreamHandler)

// Interaction endpoints
app.post('/api/click', clickHandler)
app.post('/api/click-selector', clickSelectorHandler)
app.post('/api/type', typeHandler)

// State endpoints
app.get('/api/state', stateHandler)
app.get('/api/cookies', cookiesHandler)
app.get('/api/scripts', scriptsHandler)

// Browser management
app.post('/api/close-browser', async (_req, res) => {
  try {
    await closeBrowser()
    res.json({ success: true, message: 'Browser closed' })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: message })
  }
})

// Analysis endpoint
app.post('/api/analyze', analyzeHandler)

// Start server
app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`)
})
