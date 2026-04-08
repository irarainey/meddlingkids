/**
 * Composable that derives graph nodes, edges, filtering, and stats
 * from raw network requests and the structured report.
 */

import { computed, type Ref } from 'vue'
import type { NetworkRequest, StructuredReport } from '../../types'
import { baseDomain } from '../../utils'
import {
  type TrackerCategory,
  type ViewMode,
  type GraphNode,
  type GraphEdge,
  lookupCategory,
  FIRST_PARTY_ALIASES,
  CATEGORY_LABELS,
  CATEGORY_COLOURS,
  RESOURCE_TYPE_META,
} from './tracker-graph-constants'

export interface UseGraphDataOptions {
  networkRequests: Ref<NetworkRequest[]>
  structuredReport: Ref<StructuredReport | null>
  analyzedUrl: Ref<string>
  viewMode: Ref<ViewMode>
  activeCategory: Ref<TrackerCategory | null>
  selectedNode: Ref<GraphNode | null>
}

export function useGraphData(opts: UseGraphDataOptions) {
  const {
    networkRequests,
    structuredReport,
    analyzedUrl,
    viewMode,
    activeCategory,
    selectedNode,
  } = opts

  /**
   * Build a domain → tracker-category lookup from the structured report.
   */
  const domainCategoryMap = computed<Map<string, TrackerCategory>>(() => {
    const map = new Map<string, TrackerCategory>()
    const report = structuredReport.value
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
      return new URL(analyzedUrl.value).hostname
    } catch {
      return 'origin'
    }
  })

  /**
   * The base (registrable) domain of the origin, used to
   * detect first-party subdomains that share the same base.
   */
  const originBaseDomain = computed(() => baseDomain(originDomain.value))

  /**
   * Set of base domains that should be treated as first-party
   * for the current origin, including the origin itself and any
   * aliases declared in FIRST_PARTY_ALIASES.
   */
  const firstPartyBases = computed(() => {
    const base = originBaseDomain.value
    const set = new Set<string>([base])
    const aliases = FIRST_PARTY_ALIASES[base]
    if (aliases) {
      for (const a of aliases) set.add(a)
    }
    return set
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
    const fpBases = firstPartyBases.value
    const catMap = domainCategoryMap.value

    nodeMap.set(origin, {
      id: origin,
      label: origin,
      category: 'origin',
      requestCount: 0,
      isThirdParty: false,
    })

    for (const req of networkRequests.value) {
      const target = req.domain
      if (!target || target === 'unknown') continue

      // Determine the source (initiator) domain — fall back to origin if absent
      const source = req.initiatorDomain && req.initiatorDomain !== 'unknown'
        ? req.initiatorDomain
        : origin

      // Ensure source node exists
      if (!nodeMap.has(source)) {
        const isOrigin = source === origin
        const isFirstParty = !isOrigin && fpBases.has(baseDomain(source))
        nodeMap.set(source, {
          id: source,
          label: source,
          category: isOrigin ? 'origin' : isFirstParty ? 'first-party' : lookupCategory(source, catMap),
          requestCount: 0,
          isThirdParty: isOrigin || isFirstParty ? false : source !== origin,
        })
      }

      // Ensure target node exists and bump its request count
      if (!nodeMap.has(target)) {
        const isOrigin = target === origin
        const isFirstParty = !isOrigin && fpBases.has(baseDomain(target))
        nodeMap.set(target, {
          id: target,
          label: target,
          category: isOrigin ? 'origin' : isFirstParty ? 'first-party' : lookupCategory(target, catMap),
          requestCount: 0,
          isThirdParty: isOrigin || isFirstParty ? false : req.isThirdParty,
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
  })

  /** Summary statistics shown above the graph. */
  const stats = computed(() => {
    const { nodes, edges } = filteredGraphData.value
    const thirdParty = nodes.filter(n => n.isThirdParty).length
    const preConsentEdges = edges.filter(e => e.preConsent).length
    return { totalNodes: nodes.length, thirdParty, totalEdges: edges.length, preConsentEdges }
  })

  /** Categories that have at least one node in the full (unfiltered) graph. */
  const presentCategories = computed(() => {
    const cats = new Set<TrackerCategory>()
    for (const n of graphData.value.nodes) cats.add(n.category)
    return cats
  })

  /**
   * Apply the active view mode filter to the full graph data.
   * Returns a new node/edge set with only the relevant subset.
   */
  const filteredGraphData = computed(() => {
    const { nodes, edges } = graphData.value
    const mode = viewMode.value
    const catFilter = activeCategory.value

    // 1. View-mode filter
    let modeNodes = nodes
    let modeEdges = edges

    if (mode !== 'all') {
      if (mode === 'third-party') {
        const thirdPartyIds = new Set(nodes.filter(n => n.isThirdParty).map(n => n.id))
        modeEdges = edges.filter(e => thirdPartyIds.has(e.sourceId) || thirdPartyIds.has(e.targetId))
      } else {
        // pre-consent
        modeEdges = edges.filter(e => e.preConsent)
      }

      const referencedIds = new Set<string>()
      for (const e of modeEdges) {
        referencedIds.add(e.sourceId)
        referencedIds.add(e.targetId)
      }
      referencedIds.add(originDomain.value)
      modeNodes = nodes.filter(n => referencedIds.has(n.id))
    }

    // 2. Category filter — trace full path chains from origin
    //    through any intermediate categories to nodes of the
    //    selected category.  Reverse-BFS from target nodes finds
    //    every ancestor on a path leading to them, so chains like
    //    origin → advertising → social are kept when "Social" is
    //    selected, but branches ending at other categories are pruned.
    if (catFilter !== null) {
      // Target node IDs (the selected category)
      const targetIds = new Set(
        modeNodes.filter(n => n.category === catFilter).map(n => n.id),
      )

      // Build a reverse adjacency list (targetId → set of sourceIds)
      const reverseAdj = new Map<string, string[]>()
      for (const e of modeEdges) {
        let sources = reverseAdj.get(e.targetId)
        if (!sources) { sources = []; reverseAdj.set(e.targetId, sources) }
        sources.push(e.sourceId)
      }

      // BFS backwards from every target node to discover all ancestors
      const reachable = new Set<string>(targetIds)
      const queue = [...targetIds]
      while (queue.length > 0) {
        const current = queue.shift()!
        const sources = reverseAdj.get(current)
        if (sources) {
          for (const src of sources) {
            if (!reachable.has(src)) {
              reachable.add(src)
              queue.push(src)
            }
          }
        }
      }
      reachable.add(originDomain.value)

      // Keep only edges and nodes on the discovered paths
      modeEdges = modeEdges.filter(e => reachable.has(e.sourceId) && reachable.has(e.targetId))
      const edgeNodeIds = new Set<string>()
      for (const e of modeEdges) {
        edgeNodeIds.add(e.sourceId)
        edgeNodeIds.add(e.targetId)
      }
      edgeNodeIds.add(originDomain.value)
      modeNodes = modeNodes.filter(n => edgeNodeIds.has(n.id))
    }

    return { nodes: modeNodes, edges: modeEdges }
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

  /** Resource-type breakdown for the currently selected domain. */
  const selectedResourceBreakdown = computed(() => {
    if (!selectedNode.value) return []
    const domain = selectedNode.value.id
    const counts = new Map<string, number>()

    for (const req of networkRequests.value) {
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

  /** Category breakdown for the stats overlay. */
  const graphStatsOverlay = computed(() => {
    const { nodes } = filteredGraphData.value
    const counts = new Map<TrackerCategory, number>()
    for (const n of nodes) {
      counts.set(n.category, (counts.get(n.category) ?? 0) + 1)
    }
    return Array.from(counts.entries())
      .map(([cat, count]) => ({
        category: cat,
        label: CATEGORY_LABELS[cat],
        colour: CATEGORY_COLOURS[cat],
        count,
      }))
      .sort((a, b) => b.count - a.count)
  })

  return {
    domainCategoryMap,
    originDomain,
    originBaseDomain,
    firstPartyBases,
    graphData,
    stats,
    presentCategories,
    filteredGraphData,
    selectedConnections,
    selectedResourceBreakdown,
    graphStatsOverlay,
  }
}
