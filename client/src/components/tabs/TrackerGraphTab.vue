<script setup lang="ts">
/**
 * Interactive force-directed network graph showing domain-to-domain
 * tracker relationships derived from captured network requests.
 */

import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  select,
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  zoom as d3Zoom,
  drag as d3Drag,
  max,
  scaleLinear,
  scaleSqrt,
  zoomIdentity,
} from 'd3'
import type {
  Simulation,
  SimulationNodeDatum,
  SimulationLinkDatum,
  DragBehavior,
  SubjectPosition,
  ZoomBehavior,
} from 'd3'
import type { NetworkRequest, StructuredReport } from '../../types'

// ============================================================================
// Types
// ============================================================================

/** Category label used to colour-code graph nodes. */
type TrackerCategory = 'origin' | 'analytics' | 'advertising' | 'social' | 'identity' | 'other'

/** Available graph view modes. */
type ViewMode = 'all' | 'third-party' | 'pre-consent'

/** A node in the tracker relationship graph. */
interface GraphNode extends SimulationNodeDatum {
  id: string
  label: string
  category: TrackerCategory
  requestCount: number
  isThirdParty: boolean
}

/** A directed edge between two domains. */
interface GraphEdge extends SimulationLinkDatum<GraphNode> {
  sourceId: string
  targetId: string
  weight: number
  preConsent: boolean
}

// ============================================================================
// Props
// ============================================================================

const props = defineProps<{
  /** Raw (un-filtered) network requests from the analysis */
  networkRequests: NetworkRequest[]
  /** Structured report used to classify domains by tracker category */
  structuredReport: StructuredReport | null
  /** The URL that was analysed (used to identify the origin node) */
  analyzedUrl: string
}>()

// ============================================================================
// Colours & layout constants
// ============================================================================

const CATEGORY_COLOURS: Record<TrackerCategory, string> = {
  origin: '#22c55e',
  analytics: '#3b82f6',
  advertising: '#ef4444',
  social: '#a855f7',
  identity: '#f59e0b',
  other: '#6b7280',
}

const CATEGORY_LABELS: Record<TrackerCategory, string> = {
  origin: 'Origin Site',
  analytics: 'Analytics',
  advertising: 'Advertising',
  social: 'Social Media',
  identity: 'Identity Resolution',
  other: 'Other',
}

// ============================================================================
// Refs
// ============================================================================

const svgRef = ref<SVGSVGElement | null>(null)
const minimapRef = ref<HTMLCanvasElement | null>(null)
const hoveredNode = ref<GraphNode | null>(null)
const selectedNode = ref<GraphNode | null>(null)
const isFullscreen = ref(false)
const viewMode = ref<ViewMode>('all')
const showExplanation = ref(true)

const VIEW_MODE_LABELS: Record<ViewMode, string> = {
  all: 'All Domains',
  'third-party': 'Third-Party Only',
  'pre-consent': 'Pre-Consent Only',
}

const VIEW_MODE_DESCRIPTIONS: Record<ViewMode, string> = {
  all: 'Every domain contacted during the analysis, including first-party resources.',
  'third-party': 'Only third-party domains — hides first-party requests to highlight the external tracker ecosystem.',
  'pre-consent': 'Only connections that occurred before consent was granted — these may violate GDPR requirements.',
}

/** Debounce timer for resize-triggered re-renders. */
let resizeTimer: ReturnType<typeof setTimeout> | null = null
/** Prevents concurrent or re-entrant renderGraph() calls. */
let isRendering = false
/** Last rendered dimensions — skip re-render when unchanged. */
let lastWidth = 0
let lastHeight = 0
/** Label-visibility threshold for the current render. */
let currentLabelThreshold = 3
/** Current zoom transform for minimap viewport calculation. */
let currentTransform = { x: 0, y: 0, k: 1 }
/** D3 zoom behaviour reference for programmatic panning (minimap click). */
let zoomRef: ZoomBehavior<SVGSVGElement, unknown> | null = null
/** Last-computed minimap coordinate mapping for click handling. */
let minimapMapping: { minX: number; minY: number; scale: number; offsetX: number; offsetY: number } | null = null

/**
 * Toggle fullscreen mode.
 * Pauses the ResizeObserver during the transition to prevent layout
 * oscillation, waits for the DOM to settle, then re-renders once.
 */
function toggleFullscreen(): void {
  // Pause observer to avoid resize → render → resize loop
  if (resizeObserver) resizeObserver.disconnect()
  if (resizeTimer) { clearTimeout(resizeTimer); resizeTimer = null }

  isFullscreen.value = !isFullscreen.value

  // Wait for Vue to flush the DOM change, then give the browser an
  // extra frame to finish layout before re-rendering the graph.
  nextTick(() => {
    requestAnimationFrame(() => {
      // Reset dimension cache so the re-render isn't skipped
      lastWidth = 0
      lastHeight = 0
      renderGraph()
      // Re-connect observer after the render has stabilised
      if (resizeObserver && svgRef.value) {
        resizeObserver.observe(svgRef.value)
      }
    })
  })
}

/** Close fullscreen on Escape key. */
function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape' && isFullscreen.value) {
    toggleFullscreen()
  }
}

// ============================================================================
// Computed graph data
// ============================================================================

/**
 * Build a domain → tracker-category lookup from the structured report.
 */
const domainCategoryMap = computed<Map<string, TrackerCategory>>(() => {
  const map = new Map<string, TrackerCategory>()
  const report = props.structuredReport
  if (!report) return map

  const categories: { key: TrackerCategory; entries: { domains: string[] }[] }[] = [
    { key: 'analytics', entries: report.trackingTechnologies.analytics },
    { key: 'advertising', entries: report.trackingTechnologies.advertising },
    { key: 'social', entries: report.trackingTechnologies.socialMedia },
    { key: 'identity', entries: report.trackingTechnologies.identityResolution },
    { key: 'other', entries: report.trackingTechnologies.other },
  ]

  for (const { key, entries } of categories) {
    for (const entry of entries) {
      for (const domain of entry.domains) {
        map.set(domain, key)
      }
    }
  }
  return map
})

/**
 * Extract the origin domain from the analysed URL.
 */
const originDomain = computed(() => {
  try {
    return new URL(props.analyzedUrl).hostname
  } catch {
    return 'origin'
  }
})

/**
 * Derive the node and edge lists from the raw network requests.
 */
const graphData = computed(() => {
  const nodeMap = new Map<string, GraphNode>()
  const edgeKey = (src: string, tgt: string) => `${src}>>>${tgt}`
  const edgeMap = new Map<string, GraphEdge>()

  // Ensure origin node always exists
  const origin = originDomain.value

  nodeMap.set(origin, {
    id: origin,
    label: origin,
    category: 'origin',
    requestCount: 0,
    isThirdParty: false,
  })

  for (const req of props.networkRequests) {
    const target = req.domain
    if (!target || target === 'unknown') continue

    // Determine the source (initiator) domain — fall back to origin if absent
    const source = req.initiatorDomain && req.initiatorDomain !== 'unknown'
      ? req.initiatorDomain
      : origin

    // Ensure source node exists
    if (!nodeMap.has(source)) {
      nodeMap.set(source, {
        id: source,
        label: source,
        category: source === origin ? 'origin' : lookupCategory(source),
        requestCount: 0,
        isThirdParty: source !== origin,
      })
    }

    // Ensure target node exists and bump its request count
    if (!nodeMap.has(target)) {
      nodeMap.set(target, {
        id: target,
        label: target,
        category: target === origin ? 'origin' : lookupCategory(target),
        requestCount: 0,
        isThirdParty: req.isThirdParty,
      })
    }
    nodeMap.get(target)!.requestCount++

    // Skip self-loops
    if (source === target) continue

    // Add or aggregate edge
    const key = edgeKey(source, target)
    const existing = edgeMap.get(key)
    if (existing) {
      existing.weight++
      if (req.preConsent) existing.preConsent = true
    } else {
      edgeMap.set(key, {
        sourceId: source,
        targetId: target,
        source: source,
        target: target,
        weight: 1,
        preConsent: Boolean(req.preConsent),
      })
    }
  }

  return {
    nodes: Array.from(nodeMap.values()),
    edges: Array.from(edgeMap.values()),
  }

  function lookupCategory(domain: string): TrackerCategory {
    // Exact match first
    const direct = domainCategoryMap.value.get(domain)
    if (direct) return direct
    // Try matching the parent domain (e.g. "pixel.facebook.com" → "facebook.com")
    const parts = domain.split('.')
    if (parts.length > 2) {
      const parent = parts.slice(-2).join('.')
      const parentMatch = domainCategoryMap.value.get(parent)
      if (parentMatch) return parentMatch
    }
    return 'other'
  }
})

/** Summary statistics shown above the graph. */
const stats = computed(() => {
  const { nodes, edges } = filteredGraphData.value
  const thirdParty = nodes.filter(n => n.isThirdParty).length
  const preConsentEdges = edges.filter(e => e.preConsent).length
  return { totalNodes: nodes.length, thirdParty, totalEdges: edges.length, preConsentEdges }
})

/**
 * Apply the active view mode filter to the full graph data.
 * Returns a new node/edge set with only the relevant subset.
 */
const filteredGraphData = computed(() => {
  const { nodes, edges } = graphData.value
  const mode = viewMode.value

  if (mode === 'all') return { nodes, edges }

  let filteredEdges: GraphEdge[]
  if (mode === 'third-party') {
    // Keep edges where at least one endpoint is third-party
    filteredEdges = edges.filter(e => {
      const src = nodes.find(n => n.id === e.sourceId)
      const tgt = nodes.find(n => n.id === e.targetId)
      return (src?.isThirdParty || tgt?.isThirdParty)
    })
  } else {
    // pre-consent: keep only pre-consent edges
    filteredEdges = edges.filter(e => e.preConsent)
  }

  // Collect nodes referenced by surviving edges, always include origin
  const referencedIds = new Set<string>()
  for (const e of filteredEdges) {
    referencedIds.add(e.sourceId)
    referencedIds.add(e.targetId)
  }
  const origin = originDomain.value
  referencedIds.add(origin)

  const filteredNodes = nodes.filter(n => referencedIds.has(n.id))
  return { nodes: filteredNodes, edges: filteredEdges }
})

// ============================================================================
// D3 Simulation
// ============================================================================

let simulation: Simulation<GraphNode, GraphEdge> | null = null
let resizeObserver: ResizeObserver | null = null
/** Tracks whether a RAF tick is already scheduled. */
let tickScheduled = false
/** Render (or re-render) the force-directed graph inside the SVG element. */
function renderGraph() {
  // Guard against overlapping renders
  if (isRendering) return
  isRendering = true

  try {
    renderGraphInner()
  } finally {
    isRendering = false
  }
}

function renderGraphInner() {
  const svg = svgRef.value
  if (!svg) return

  const { nodes, edges } = filteredGraphData.value
  if (nodes.length === 0) return

  // Stop any running simulation first
  if (simulation) { simulation.stop(); simulation = null }
  tickScheduled = false

  const width = svg.clientWidth || 900
  const height = svg.clientHeight || 500

  // Skip re-render when dimensions haven't changed and we already have
  // a rendered graph (avoids unnecessary full rebuilds on no-op resizes)
  if (width === lastWidth && height === lastHeight && svg.childElementCount > 0) return
  lastWidth = width
  lastHeight = height

  // Clear previous render
  select(svg).selectAll('*').remove()

  const svgSel = select(svg)
    .attr('viewBox', `0 0 ${width} ${height}`)

  // Container for zoom/pan
  const container = svgSel.append('g')

  // Zoom behaviour
  zoomRef = d3Zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.2, 4])
    .on('zoom', (event) => {
      container.attr('transform', event.transform)
      currentTransform = { x: event.transform.x, y: event.transform.y, k: event.transform.k }
    })
  svgSel.call(zoomRef)

  // Arrow marker for directed edges
  svgSel.append('defs').append('marker')
    .attr('id', 'arrowhead')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 20)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#4b5563')

  // Pre-consent arrow marker (orange)
  svgSel.select('defs').append('marker')
    .attr('id', 'arrowhead-precon')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 20)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#f59e0b')

  // Edge scale for stroke width
  const maxWeight = max(edges, e => e.weight) ?? 1
  const strokeScale = scaleLinear().domain([1, maxWeight]).range([1, 4])

  // Draw edges
  const linkGroup = container.append('g').attr('class', 'links')
  const linkSel = linkGroup.selectAll<SVGLineElement, GraphEdge>('line')
    .data(edges)
    .join('line')
    .attr('stroke', d => d.preConsent ? '#f59e0b' : '#4b5563')
    .attr('stroke-width', d => strokeScale(d.weight))
    .attr('stroke-dasharray', d => d.preConsent ? '5,3' : 'none')
    .attr('marker-end', d => d.preConsent ? 'url(#arrowhead-precon)' : 'url(#arrowhead)')
    .attr('opacity', 0.6)

  // Node radius scale
  const maxReq = max(nodes, n => n.requestCount) ?? 1
  const radiusScale = scaleSqrt().domain([0, maxReq]).range([6, 24])

  /** Minimum request count to show a persistent label. */
  const labelThreshold = Math.max(3, Math.ceil(nodes.length * 0.08))
  currentLabelThreshold = labelThreshold

  // Draw nodes
  const nodeGroup = container.append('g').attr('class', 'nodes')
  const nodeSel = nodeGroup.selectAll<SVGCircleElement, GraphNode>('circle')
    .data(nodes, d => d.id)
    .join('circle')
    .attr('r', d => d.category === 'origin' ? 16 : radiusScale(d.requestCount))
    .attr('fill', d => CATEGORY_COLOURS[d.category])
    .attr('stroke', '#1e2235')
    .attr('stroke-width', 1.5)
    .attr('cursor', 'pointer')
    .on('mouseover', (_event, d) => {
      hoveredNode.value = d
      // Show label on hover for nodes that lack a persistent label
      labelSel.filter(n => n.id === d.id).attr('opacity', 1)
    })
    .on('mouseout', (_event, d) => {
      hoveredNode.value = null
      // Restore original opacity
      labelSel.filter(n => n.id === d.id)
        .attr('opacity', n => showLabel(n) ? 1 : 0)
    })
    .on('click', (_event, d) => {
      selectedNode.value = selectedNode.value?.id === d.id ? null : d
    })

  /** Whether a node gets a persistent label. */
  function showLabel(d: GraphNode): boolean {
    return d.category === 'origin' || d.requestCount >= labelThreshold
  }

  // Labels — only permanently visible for origin + high-activity nodes
  const labelGroup = container.append('g').attr('class', 'labels')
  const labelSel = labelGroup.selectAll<SVGTextElement, GraphNode>('text')
    .data(nodes)
    .join('text')
    .text(d => truncateLabel(d.label))
    .attr('font-size', d => d.category === 'origin' ? '11px' : '9px')
    .attr('fill', '#c7d2fe')
    .attr('text-anchor', 'middle')
    .attr('dy', d => -(d.category === 'origin' ? 20 : radiusScale(d.requestCount) + 6))
    .attr('pointer-events', 'none')
    .attr('opacity', d => showLabel(d) ? 1 : 0)

  // Force simulation — increased alphaDecay for faster convergence
  simulation = forceSimulation<GraphNode, GraphEdge>(nodes)
    .alphaDecay(0.05)
    .force('link', forceLink<GraphNode, GraphEdge>(edges).id(d => d.id).distance(100))
    .force('charge', forceManyBody().strength(-200))
    .force('center', forceCenter(width / 2, height / 2))
    .force('collision', forceCollide<GraphNode>().radius(d => radiusScale(d.requestCount) + 8))
    .on('tick', () => {
      // Throttle DOM updates to one per animation frame
      if (tickScheduled) return
      tickScheduled = true
      requestAnimationFrame(() => {
        tickScheduled = false
        linkSel
          .attr('x1', d => (d.source as GraphNode).x ?? 0)
          .attr('y1', d => (d.source as GraphNode).y ?? 0)
          .attr('x2', d => (d.target as GraphNode).x ?? 0)
          .attr('y2', d => (d.target as GraphNode).y ?? 0)

        nodeSel
          .attr('cx', d => d.x ?? 0)
          .attr('cy', d => d.y ?? 0)

        labelSel
          .attr('x', d => d.x ?? 0)
          .attr('y', d => d.y ?? 0)

        renderMinimap(nodes, edges)
      })
    })

  // Wire drag behaviour now that simulation is initialised
  nodeSel.call(drag(simulation))

  // Re-apply subgraph highlight if a node was selected before re-render
  if (selectedNode.value) applyHighlight()

}

/**
 * Create a D3 drag behaviour for graph nodes.
 */
function drag(
  sim: Simulation<GraphNode, GraphEdge>,
): DragBehavior<SVGCircleElement, GraphNode, GraphNode | SubjectPosition> {
  return d3Drag<SVGCircleElement, GraphNode>()
    .on('start', (event, d) => {
      if (!event.active) sim.alphaTarget(0.3).restart()
      d.fx = d.x
      d.fy = d.y
    })
    .on('drag', (event, d) => {
      d.fx = event.x
      d.fy = event.y
    })
    .on('end', (event, d) => {
      if (!event.active) sim.alphaTarget(0)
      d.fx = null
      d.fy = null
    })
}

// ============================================================================
// Subgraph Highlighting
// ============================================================================

/**
 * Dim unrelated nodes and edges when a node is selected, or restore
 * defaults when the selection is cleared.
 */
function applyHighlight(): void {
  const svg = svgRef.value
  if (!svg) return

  const svgSel = select(svg)
  const circlesSel = svgSel.selectAll<SVGCircleElement, GraphNode>('.nodes circle')
  const linesSel = svgSel.selectAll<SVGLineElement, GraphEdge>('.links line')
  const textsSel = svgSel.selectAll<SVGTextElement, GraphNode>('.labels text')

  const sel = selectedNode.value
  if (!sel) {
    // Restore defaults
    circlesSel.attr('opacity', 1)
    linesSel.attr('opacity', 0.6)
    textsSel.attr('opacity', (d: GraphNode) =>
      d.category === 'origin' || d.requestCount >= currentLabelThreshold ? 1 : 0)
    return
  }

  // Build set of directly connected node IDs
  const { edges } = filteredGraphData.value
  const connectedIds = new Set<string>([sel.id])
  for (const e of edges) {
    if (e.sourceId === sel.id) connectedIds.add(e.targetId)
    if (e.targetId === sel.id) connectedIds.add(e.sourceId)
  }

  circlesSel.attr('opacity', (d: GraphNode) => connectedIds.has(d.id) ? 1 : 0.12)
  linesSel.attr('opacity', (d: GraphEdge) =>
    d.sourceId === sel.id || d.targetId === sel.id ? 0.85 : 0.04)
  textsSel.attr('opacity', (d: GraphNode) => connectedIds.has(d.id) ? 1 : 0.04)
}

// ============================================================================
// Minimap
// ============================================================================

/**
 * Draw a small overview of the graph with a viewport rectangle.
 * Called on every simulation tick so node positions stay in sync.
 */
function renderMinimap(nodes: GraphNode[], edges: GraphEdge[]): void {
  const canvas = minimapRef.value
  if (!canvas || nodes.length < 6) return

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const mw = canvas.width
  const mh = canvas.height

  // Compute data extent
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const n of nodes) {
    const x = n.x ?? 0
    const y = n.y ?? 0
    if (x < minX) minX = x
    if (y < minY) minY = y
    if (x > maxX) maxX = x
    if (y > maxY) maxY = y
  }
  const pad = 40
  minX -= pad; minY -= pad; maxX += pad; maxY += pad
  const dataW = maxX - minX || 1
  const dataH = maxY - minY || 1

  const scale = Math.min(mw / dataW, mh / dataH)
  const offsetX = (mw - dataW * scale) / 2
  const offsetY = (mh - dataH * scale) / 2

  // Store mapping for the click handler
  minimapMapping = { minX, minY, scale, offsetX, offsetY }

  const toMx = (x: number) => (x - minX) * scale + offsetX
  const toMy = (y: number) => (y - minY) * scale + offsetY

  // Clear & background
  ctx.clearRect(0, 0, mw, mh)
  ctx.fillStyle = 'rgba(21, 24, 37, 0.9)'
  ctx.fillRect(0, 0, mw, mh)

  // Edges
  ctx.strokeStyle = 'rgba(75, 85, 99, 0.35)'
  ctx.lineWidth = 0.5
  ctx.beginPath()
  for (const e of edges) {
    const src = e.source as GraphNode
    const tgt = e.target as GraphNode
    ctx.moveTo(toMx(src.x ?? 0), toMy(src.y ?? 0))
    ctx.lineTo(toMx(tgt.x ?? 0), toMy(tgt.y ?? 0))
  }
  ctx.stroke()

  // Nodes
  for (const n of nodes) {
    ctx.fillStyle = CATEGORY_COLOURS[n.category]
    ctx.globalAlpha = n.category === 'origin' ? 1 : 0.8
    ctx.beginPath()
    ctx.arc(toMx(n.x ?? 0), toMy(n.y ?? 0), n.category === 'origin' ? 3 : 2, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.globalAlpha = 1

  // Viewport rectangle
  const svg = svgRef.value
  if (svg) {
    const svgW = svg.clientWidth || 900
    const svgH = svg.clientHeight || 500
    const t = currentTransform
    const vx1 = -t.x / t.k
    const vy1 = -t.y / t.k
    const vx2 = (svgW - t.x) / t.k
    const vy2 = (svgH - t.y) / t.k

    ctx.strokeStyle = 'rgba(99, 102, 241, 0.8)'
    ctx.lineWidth = 1.5
    ctx.strokeRect(toMx(vx1), toMy(vy1), (vx2 - vx1) * scale, (vy2 - vy1) * scale)
  }
}

/**
 * Handle click on the minimap — pan the main graph to centre
 * on the corresponding data coordinate.
 */
function onMinimapClick(event: MouseEvent): void {
  const canvas = minimapRef.value
  const svg = svgRef.value
  if (!canvas || !svg || !zoomRef || !minimapMapping) return

  const rect = canvas.getBoundingClientRect()
  const mx = event.clientX - rect.left
  const my = event.clientY - rect.top

  const { minX, minY, scale, offsetX, offsetY } = minimapMapping
  const dataX = (mx - offsetX) / scale + minX
  const dataY = (my - offsetY) / scale + minY

  const svgW = svg.clientWidth || 900
  const svgH = svg.clientHeight || 500
  const k = currentTransform.k

  const newTransform = zoomIdentity
    .translate(svgW / 2 - dataX * k, svgH / 2 - dataY * k)
    .scale(k)

  select<SVGSVGElement, unknown>(svg)
    .call(zoomRef.transform, newTransform)
}

/** Shorten long domain labels for legibility. */
function truncateLabel(domain: string): string {
  return domain.length > 28 ? domain.slice(0, 25) + '…' : domain
}

// ============================================================================
// Lifecycle & Reactivity
// ============================================================================

onMounted(() => {
  renderGraph()
  resizeObserver = new ResizeObserver(() => {
    // Debounce resize-triggered re-renders (250 ms is long enough to
    // let fullscreen layout changes settle without causing a loop).
    if (resizeTimer) clearTimeout(resizeTimer)
    resizeTimer = setTimeout(() => {
      resizeTimer = null
      renderGraph()
    }, 250)
  })
  if (svgRef.value) resizeObserver.observe(svgRef.value)
  document.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  if (simulation) { simulation.stop(); simulation = null }
  if (resizeObserver) { resizeObserver.disconnect(); resizeObserver = null }
  if (resizeTimer) { clearTimeout(resizeTimer); resizeTimer = null }
  document.removeEventListener('keydown', onKeydown)
})

watch(filteredGraphData, () => {
  // Data changed — reset dimension cache so renderGraph performs a full rebuild
  lastWidth = 0
  lastHeight = 0
  renderGraph()
})

watch(selectedNode, () => {
  applyHighlight()
})

/** Connected domains for the selected node (shown in detail panel). */
const selectedConnections = computed(() => {
  if (!selectedNode.value) return []
  const id = selectedNode.value.id
  const { edges } = graphData.value
  return edges
    .filter(e => e.sourceId === id || e.targetId === id)
    .map(e => ({
      domain: e.sourceId === id ? e.targetId : e.sourceId,
      direction: e.sourceId === id ? 'outbound' as const : 'inbound' as const,
      weight: e.weight,
      preConsent: e.preConsent,
    }))
    .sort((a, b) => b.weight - a.weight)
})

/** Human-friendly labels and icons for common Playwright resource types. */
const RESOURCE_TYPE_META: Record<string, { icon: string; label: string }> = {
  script: { icon: '📜', label: 'Scripts' },
  stylesheet: { icon: '🎨', label: 'Stylesheets' },
  image: { icon: '🖼️', label: 'Images' },
  font: { icon: '🔤', label: 'Fonts' },
  xhr: { icon: '📡', label: 'XHR' },
  fetch: { icon: '📡', label: 'Fetch' },
  document: { icon: '📄', label: 'Documents' },
  iframe: { icon: '🪟', label: 'IFrames' },
  media: { icon: '🎬', label: 'Media' },
  websocket: { icon: '🔌', label: 'WebSocket' },
  ping: { icon: '📍', label: 'Pings' },
  manifest: { icon: '📋', label: 'Manifests' },
  preflight: { icon: '✈️', label: 'Preflight' },
  other: { icon: '📦', label: 'Other' },
}

/** Resource-type breakdown for the currently selected domain. */
const selectedResourceBreakdown = computed(() => {
  if (!selectedNode.value) return []
  const domain = selectedNode.value.id
  const counts = new Map<string, number>()

  for (const req of props.networkRequests) {
    if (req.domain !== domain) continue
    const type = req.resourceType || 'other'
    counts.set(type, (counts.get(type) ?? 0) + 1)
  }

  return Array.from(counts.entries())
    .map(([type, count]) => {
      const meta = RESOURCE_TYPE_META[type] ?? { icon: '📦', label: type }
      return { type, count, icon: meta.icon, label: meta.label }
    })
    .sort((a, b) => b.count - a.count)
})
</script>

<template>
  <div class="tab-content tracker-graph-tab" :class="{ fullscreen: isFullscreen }">
    <div v-if="networkRequests.length === 0" class="empty-state">
      No network request data available
    </div>
    <template v-else>
      <!-- Explanation -->
      <div v-if="showExplanation" class="graph-explanation">
        <button class="explanation-close" title="Dismiss" @click="showExplanation = false">&times;</button>
        <p>
          This graph maps the <strong>tracker ecosystem</strong> detected on the analysed page.
          Each circle is a domain, and arrows show which domain initiated requests to others.
          Larger circles mean more requests. Dashed orange lines indicate activity that occurred
          <strong>before consent</strong> was granted. Click any node for details.
        </p>
        <p class="explanation-mode">{{ VIEW_MODE_DESCRIPTIONS[viewMode] }}</p>
      </div>

      <!-- Controls bar -->
      <div class="graph-controls">
        <!-- View mode selector -->
        <div class="view-modes">
          <button
            v-for="(label, mode) in VIEW_MODE_LABELS"
            :key="mode"
            class="mode-btn"
            :class="{ active: viewMode === mode }"
            @click="viewMode = mode as ViewMode"
          >
            {{ label }}
          </button>
        </div>

        <!-- Stats -->
        <div class="graph-stats">
          <span class="stat"><strong>{{ stats.totalNodes }}</strong> domains</span>
          <span class="stat"><strong>{{ stats.thirdParty }}</strong> third-party</span>
          <span class="stat"><strong>{{ stats.totalEdges }}</strong> connections</span>
          <span v-if="stats.preConsentEdges > 0" class="stat stat-warn">
            <strong>{{ stats.preConsentEdges }}</strong> pre-consent
          </span>
        </div>

        <button class="fullscreen-btn" :title="isFullscreen ? 'Exit fullscreen' : 'Fullscreen'" @click="toggleFullscreen">
          {{ isFullscreen ? '✕' : '⛶' }}
        </button>
      </div>

      <!-- Legend -->
      <div class="graph-legend">
        <span v-for="(colour, cat) in CATEGORY_COLOURS" :key="cat" class="legend-item">
          <span class="legend-dot" :style="{ background: colour }"></span>
          {{ CATEGORY_LABELS[cat] }}
        </span>
        <span class="legend-item">
          <span class="legend-line legend-line-dashed"></span>
          Pre-consent
        </span>
      </div>

      <div v-if="filteredGraphData.nodes.length <= 1" class="empty-state">
        No connections to show in this view mode.
      </div>

      <!-- Graph container -->
      <div v-else class="graph-wrapper">
        <svg ref="svgRef" class="graph-svg"></svg>

        <!-- Minimap (overview + viewport indicator) -->
        <canvas
          v-if="filteredGraphData.nodes.length >= 6"
          ref="minimapRef"
          class="graph-minimap"
          width="160"
          height="100"
          title="Click to navigate"
          @click="onMinimapClick"
        ></canvas>

        <!-- Hover tooltip -->
        <div
          v-if="hoveredNode && !selectedNode"
          class="graph-tooltip"
        >
          <strong>{{ hoveredNode.label }}</strong>
          <span class="tooltip-cat" :style="{ color: CATEGORY_COLOURS[hoveredNode.category] }">
            {{ CATEGORY_LABELS[hoveredNode.category] }}
          </span>
          <span>{{ hoveredNode.requestCount }} request{{ hoveredNode.requestCount !== 1 ? 's' : '' }}</span>
        </div>
      </div>

      <!-- Selected-node detail panel -->
      <div v-if="selectedNode" class="detail-panel">
        <div class="detail-header">
          <span class="detail-dot" :style="{ background: CATEGORY_COLOURS[selectedNode.category] }"></span>
          <strong>{{ selectedNode.label }}</strong>
          <span class="detail-cat">{{ CATEGORY_LABELS[selectedNode.category] }}</span>
          <button class="detail-close" @click="selectedNode = null">&times;</button>
        </div>
        <div class="detail-stats">
          <span>{{ selectedNode.requestCount }} request{{ selectedNode.requestCount !== 1 ? 's' : '' }}</span>
          <span v-if="selectedNode.isThirdParty" class="third-party-badge">3rd Party</span>
        </div>
        <div v-if="selectedConnections.length > 0" class="detail-connections">
          <h4>Connections</h4>
          <div v-for="conn in selectedConnections" :key="conn.domain + conn.direction" class="conn-item">
            <span class="conn-dir">{{ conn.direction === 'outbound' ? '→' : '←' }}</span>
            <span class="conn-domain">{{ conn.domain }}</span>
            <span class="conn-weight">×{{ conn.weight }}</span>
            <span v-if="conn.preConsent" class="pre-consent-badge">Pre-consent</span>
          </div>
        </div>
        <div v-if="selectedResourceBreakdown.length > 0" class="detail-resources">
          <h4>Resource Types</h4>
          <div class="resource-grid">
            <div v-for="res in selectedResourceBreakdown" :key="res.type" class="resource-item">
              <span class="resource-icon">{{ res.icon }}</span>
              <span class="resource-label">{{ res.label }}</span>
              <span class="resource-count">{{ res.count }}</span>
            </div>
          </div>
        </div>
      </div>

      <p class="graph-hint">
        Drag nodes to rearrange. Scroll to zoom. Click a node for details. Press <kbd>Esc</kbd> to exit fullscreen.
      </p>
    </template>
  </div>
</template>

<style scoped>
.tracker-graph-tab {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* Fullscreen mode */
.tracker-graph-tab.fullscreen {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: #1a1a2e;
  border: none;
  border-radius: 0;
  margin: 0;
  padding: 1rem;
  overflow-y: auto;
}

.tracker-graph-tab.fullscreen .graph-svg {
  height: calc(100vh - 200px);
}

/* Explanation */
.graph-explanation {
  position: relative;
  background: #2a2f45;
  border: 1px solid #3d4663;
  border-left: 3px solid #6366f1;
  border-radius: 6px;
  padding: 0.6rem 2rem 0.6rem 0.75rem;
  font-size: 0.85rem;
  color: #9ca3af;
  line-height: 1.5;
}

.graph-explanation p {
  margin: 0 0 0.3rem;
}

.graph-explanation p:last-child {
  margin-bottom: 0;
}

.graph-explanation strong {
  color: #e0e7ff;
}

.explanation-mode {
  font-style: italic;
  font-size: 0.8rem;
}

.explanation-close {
  position: absolute;
  top: 0.3rem;
  right: 0.4rem;
  background: transparent;
  border: none;
  color: #6b7280;
  font-size: 1rem;
  cursor: pointer;
  padding: 0 0.3rem;
  line-height: 1;
}

.explanation-close:hover {
  color: #e0e7ff;
}

/* Controls bar */
.graph-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
}

.view-modes {
  display: flex;
  gap: 0.25rem;
}

.mode-btn {
  padding: 0.3rem 0.6rem;
  font-size: 0.8rem;
  border: 1px solid #3d4663;
  border-radius: 4px;
  background: #1e2235;
  color: #9ca3af;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.mode-btn:hover {
  border-color: #6366f1;
  color: #c7d2fe;
}

.mode-btn.active {
  background: #3730a3;
  border-color: #6366f1;
  color: #e0e7ff;
  font-weight: 600;
}

/* Stats bar */
.graph-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: center;
  font-size: 0.9rem;
  color: #9ca3af;
  margin-left: auto;
}

.stat strong {
  color: #e0e7ff;
}

.stat-warn strong {
  color: #f59e0b;
}

.fullscreen-btn {
  margin-left: auto;
  background: #2a2f45;
  border: 1px solid #3d4663;
  color: #9ca3af;
  font-size: 1.1rem;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  cursor: pointer;
  line-height: 1;
  transition: color 0.2s, border-color 0.2s;
}

.fullscreen-btn:hover {
  color: #e0e7ff;
  border-color: #6366f1;
}

/* Legend */
.graph-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  font-size: 0.8rem;
  color: #9ca3af;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.legend-line {
  width: 18px;
  height: 2px;
  background: #4b5563;
  display: inline-block;
}

.legend-line-dashed {
  background: repeating-linear-gradient(
    90deg,
    #f59e0b 0 5px,
    transparent 5px 8px
  );
}

/* Graph area */
.graph-wrapper {
  position: relative;
  border: 1px solid #3d4663;
  border-radius: 6px;
  background: #151825;
  overflow: hidden;
}

.graph-svg {
  width: 100%;
  height: 480px;
  display: block;
}

/* Tooltip */
.graph-tooltip {
  position: absolute;
  top: 12px;
  left: 12px;
  background: #2a2f45;
  border: 1px solid #3d4663;
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  font-size: 0.85rem;
  pointer-events: none;
  z-index: 10;
  color: #e0e7ff;
}

.tooltip-cat {
  font-size: 0.75rem;
  font-weight: 600;
}

/* Detail panel */
.detail-panel {
  background: #2a2f45;
  border: 1px solid #3d4663;
  border-radius: 6px;
  padding: 0.75rem 1rem;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
}

.detail-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.detail-cat {
  font-size: 0.8rem;
  color: #9ca3af;
}

.detail-close {
  margin-left: auto;
  background: transparent;
  border: none;
  color: #9ca3af;
  font-size: 1.2rem;
  cursor: pointer;
  padding: 0 0.3rem;
  line-height: 1;
}

.detail-close:hover {
  color: #e0e7ff;
}

.detail-stats {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  margin-top: 0.4rem;
  font-size: 0.85rem;
  color: #9ca3af;
}

.third-party-badge {
  background: #ef4444;
  color: white;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.75rem;
}

.detail-connections {
  margin-top: 0.75rem;
  max-height: 180px;
  overflow-y: auto;
}

.detail-connections h4 {
  margin: 0 0 0.4rem;
  font-size: 0.85rem;
  color: #e0e7ff;
}

.conn-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0;
  border-bottom: 1px solid #3d4663;
  font-size: 0.85rem;
}

.conn-item:last-child {
  border-bottom: none;
}

.conn-dir {
  color: #6b7280;
  font-size: 0.9rem;
  width: 1.2rem;
  text-align: center;
}

.conn-domain {
  color: #c7d2fe;
  word-break: break-all;
}

.conn-weight {
  color: #9ca3af;
  font-size: 0.8rem;
  margin-left: auto;
  flex-shrink: 0;
}

.pre-consent-badge {
  font-size: 0.7rem;
  font-weight: 600;
  background: #7c2d12;
  color: #fed7aa;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  flex-shrink: 0;
}

/* Resource-type breakdown */
.detail-resources {
  margin-top: 0.75rem;
}

.detail-resources h4 {
  margin: 0 0 0.4rem;
  font-size: 0.85rem;
  color: #e0e7ff;
}

.resource-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.resource-item {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  background: #1e2235;
  border: 1px solid #3d4663;
  border-radius: 4px;
  padding: 0.2rem 0.5rem;
  font-size: 0.8rem;
}

.resource-icon {
  font-size: 0.85rem;
}

.resource-label {
  color: #c7d2fe;
}

.resource-count {
  color: #9ca3af;
  font-size: 0.75rem;
  font-weight: 600;
}

/* Minimap */
.graph-minimap {
  position: absolute;
  bottom: 8px;
  right: 8px;
  border: 1px solid #3d4663;
  border-radius: 4px;
  cursor: crosshair;
  z-index: 5;
  opacity: 0.85;
  transition: opacity 0.2s;
}

.graph-minimap:hover {
  opacity: 1;
}

.graph-hint {
  font-size: 0.8rem;
  color: #6b7280;
  text-align: center;
  margin: 0;
}
</style>
