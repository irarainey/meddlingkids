# Meddling Kids

<img src="./images/logo.png" alt="Meddling Kids Logo" width="50%">

Zoinks! There's something spooky going on with these websites... but don't worry, gang! This mystery-solving machine pulls the mask off sneaky trackers and exposes the villain underneath. Feed it any URL and watch as we unmask those cookies, scripts, network requests, and shady consent dialogs. And we would have never figured it out if it wasn't for those meddling kids!

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Node](https://img.shields.io/badge/node-22%2B-green.svg)
![TypeScript](https://img.shields.io/badge/typescript-5.x-blue.svg)
![Vue](https://img.shields.io/badge/vue-3.x-brightgreen.svg)

## Features

- 📸 **Screenshot Timeline** — Captures page state at initial load, after consent, and final
- 📱 **Device Emulation** — Test as iPhone, iPad, Android, Windows Chrome, or macOS Safari
- 📋 **Consent Dialog Extraction** — Reads and reports cookie consent banner details
- 🌐 **Real-time URL Analysis** — Enter any URL and watch as tracking is exposed in real-time
- 🎯 **Privacy Score** — Scooby-Doo themed privacy rating (Zoinks! to Scooby Snack!)
- 🍪 **Cookie Detection** — Identifies all cookies including third-party trackers
- 📜 **Script Tracking** — Lists all JavaScript files loaded, grouped by domain
- 🔄 **Network Monitoring** — Captures HTTP requests with third-party filtering
- 💾 **Storage Inspection** — Reveals localStorage and sessionStorage usage
- 🤖 **AI-Powered Analysis** — Uses Azure OpenAI to analyze privacy implications

## How It Works

1. **URL Submission** — User enters a URL and selects a device type to emulate
2. **Browser Automation** — Playwright launches headless Chromium with device emulation
3. **Real-time Streaming** — Results stream to the UI via Server-Sent Events
4. **Access Check** — Detects bot protection or access denied responses
5. **Consent Detection** — AI analyzes the page for cookie consent dialogs
6. **Consent Interaction** — Attempts to click "Accept All" and captures changes
7. **Data Collection** — Captures cookies, scripts, network requests, and storage
8. **Privacy Score** — Generates a 0-100 privacy score with Scooby-Doo themed rating
9. **Privacy Analysis** — AI reviews collected data for privacy concerns

## Example Analysis Walkthrough

Let's take a look at a page from the Daily Mail (a site known for heavy tracking). Here's what the original page looks like. Wowzers! I wonder what is going on behind the scenes...

![Original Site](./images/examples/001.png)

---

So let's run an analysis and see what Meddling Kids uncovers!

![Start Analysis](./images/examples/002.png)

---

First we load up the intial page and see if it has any consent dialogs. If so we will attempt to accept consent and all cookies and track the changes.

![Detect Consent Dialog](./images/examples/003.png)

---

Once we've detected and dismissed the consent dialog, we can see the final loaded page and we can start the analysis. If there are multiple stages, the screenshots will show each step.

![Final Page](./images/examples/004.png)

---

After the analysis is complete, we get a privacy score out of 100 based on the tracking detected. The score ranges from "Zoinks!" for poor privacy to "Scooby Snack!" for excellent privacy.

![Score](./images/examples/005.png)

---

If you want to dive deeper, we get a full report showing all cookies, scripts, network requests, storage items, and AI analysis.

![Full Report](./images/examples/006.png)

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Vue 3, TypeScript, Vite |
| Backend | Express.js, TypeScript |
| Browser Automation | Playwright |
| AI | Azure OpenAI (GPT-4) |
| Communication | Server-Sent Events (SSE) |

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
│       ├── data/              # Tracking script databases
│       ├── prompts/           # AI prompt templates
│       └── utils/             # Utility functions
├── Dockerfile                 # Multi-stage production build
└── vite.config.ts             # Vite build configuration
```

## How to Run Locally

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

Edit `.env` with your OpenAI credentials. The app supports both Azure OpenAI and standard OpenAI:

**Option A: Azure OpenAI**
```env
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

**Option B: Standard OpenAI**
```env
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-4o
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

Then open a browser to http://localhost:3001.

### Run with Environment Variables

**Azure OpenAI:**
```bash
docker run -p 3001:3001 \
  -e AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/ \
  -e AZURE_OPENAI_API_KEY=your-api-key \
  -e AZURE_OPENAI_DEPLOYMENT=gpt-4o \
  meddlingkids
```

**Standard OpenAI:**
```bash
docker run -p 3001:3001 \
  -e OPENAI_API_KEY=your-api-key \
  -e OPENAI_MODEL=gpt-4o \
  meddlingkids
```

Then open http://localhost:3001 to access the app.

## Available Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start both client and server in development mode |
| `npm run dev:client` | Start only the Vite client dev server |
| `npm run dev:server` | Start only the Express server |
| `npm run build` | Build the client for production |
| `npm run preview` | Preview the production build |
| `npm run lint` | Check for lint errors |
| `npm run lint:fix` | Auto-fix lint errors |

## Project Documentation

- [Developer Guide](DEVELOPER_GUIDE.md) — Application workflow, data flow, and architecture
- [Client README](client/README.md) — Frontend architecture, components, and styling
- [Server README](server/README.md) — Backend architecture, services, and API

## License

MIT License - see [LICENSE](LICENSE) for details.