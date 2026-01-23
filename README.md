# Meddling Kids

<img src="./images/logo.png" alt="Meddling Kids Logo" width="50%">

Zoinks! There's something spooky going on with these websites... but don't worry, gang! This mystery-solving machine pulls the mask off sneaky trackers and exposes the villain underneath. Feed it any URL and watch as we unmask those cookies, scripts, network requests, and shady consent dialogs. And we would have never figured it out if it weren't for our meddling AI!

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Node](https://img.shields.io/badge/node-22%2B-green.svg)
![TypeScript](https://img.shields.io/badge/typescript-5.x-blue.svg)
![Vue](https://img.shields.io/badge/vue-3.x-brightgreen.svg)

## Features

- 🌐 **Real-time URL Analysis** — Enter any URL and watch as tracking is exposed in real-time
- 🍪 **Cookie Detection** — Identifies all cookies including third-party trackers
- 📜 **Script Tracking** — Lists all JavaScript files loaded, grouped by domain
- 🔄 **Network Monitoring** — Captures HTTP requests with third-party filtering
- 💾 **Storage Inspection** — Reveals localStorage and sessionStorage usage
- 🤖 **AI-Powered Analysis** — Uses Azure OpenAI to analyze privacy implications
- 📋 **Consent Dialog Extraction** — Reads and reports cookie consent banner details
- 📸 **Screenshot Timeline** — Captures page state at initial load, after consent, and final

## Architecture

```
meddlingkids/
├── client/                    # Vue.js 3 frontend
│   ├── src/
│   │   ├── components/        # UI components (tabs, gallery, progress)
│   │   ├── composables/       # State management (useTrackingAnalysis)
│   │   ├── types/             # TypeScript interfaces
│   │   └── utils/             # Formatting utilities
│   └── public/                # Static assets
├── server/                    # Express.js backend
│   └── src/
│       ├── routes/            # API endpoints (SSE streaming)
│       ├── services/          # Business logic (browser, analysis, consent)
│       ├── prompts/           # AI prompt templates
│       └── utils/             # Utility functions
├── Dockerfile                 # Multi-stage production build
└── vite.config.ts             # Vite build configuration
```

## Quick Start

### Prerequisites

- **Node.js 22+** (uses native TypeScript support)
- **Azure OpenAI** account with API access

### 1. Clone and Install

```bash
git clone https://github.com/irarainey/meddlingkids.git
cd meddlingkids
npm install
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your Azure OpenAI credentials:

```env
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

### 3. Run Development Server

```bash
npm run dev
```

This starts both:
- **Client**: http://localhost:5173 (Vite dev server)
- **Server**: http://localhost:3001 (Express API)

## Docker Deployment

Build and run the entire stack in a container:

### Build

```bash
docker build -t meddlingkids .
```

### Run with Environment File

```bash
docker run -p 3001:3001 --env-file .env meddlingkids
```

### Run with Environment Variables

```bash
docker run -p 3001:3001 \
  -e AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/ \
  -e AZURE_OPENAI_API_KEY=your-api-key \
  -e AZURE_OPENAI_DEPLOYMENT=gpt-4o \
  meddlingkids
```

Then open http://localhost:3001

## Available Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start both client and server in development mode |
| `npm run dev:client` | Start only the Vite client dev server |
| `npm run dev:server` | Start only the Express server |
| `npm run build` | Build the client for production |
| `npm run preview` | Preview the production build |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Yes | Your Azure OpenAI endpoint URL |
| `AZURE_OPENAI_API_KEY` | Yes | Your Azure OpenAI API key |
| `AZURE_OPENAI_DEPLOYMENT` | Yes | The deployment name (e.g., `gpt-4o`) |
| `PORT` | No | Server port (default: `3001`) |

## How It Works

1. **URL Submission** — User enters a URL to analyze
2. **Browser Automation** — Playwright launches headless Chromium to load the page
3. **Data Collection** — Captures cookies, scripts, network requests, and storage
4. **Consent Detection** — AI analyzes the page for cookie consent dialogs
5. **Consent Interaction** — Attempts to click "Accept All" and captures changes
6. **Privacy Analysis** — AI reviews collected data for privacy concerns
7. **Real-time Streaming** — Results stream to the UI via Server-Sent Events

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Vue 3, TypeScript, Vite |
| Backend | Express.js, TypeScript |
| Browser Automation | Playwright |
| AI | Azure OpenAI (GPT-4) |
| Communication | Server-Sent Events (SSE) |

## Project Documentation

- [Client README](client/README.md) — Frontend architecture, components, and styling
- [Server README](server/README.md) — Backend architecture, services, and API

## License

MIT License - see [LICENSE](LICENSE) for details.