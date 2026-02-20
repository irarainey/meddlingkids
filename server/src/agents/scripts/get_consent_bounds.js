// Return the bounding rectangle of the first visible consent dialog container.
// Called via Playwright page.evaluate() — must be a self-contained IIFE.
// Returns {left, top, right, bottom} or null if no container is found.
(() => {
    /**
     * Return bounds for an element if it is visible and large enough,
     * otherwise null.
     */
    const getBounds = (el) => {
        const rect = el.getBoundingClientRect();
        // Must be visible and at least 100×50 pixels.
        if (rect.width >= 100 && rect.height >= 50) {
            return {
                left: Math.round(rect.left),
                top: Math.round(rect.top),
                right: Math.round(rect.right),
                bottom: Math.round(rect.bottom),
            };
        }
        return null;
    };

    // ── High-confidence selectors ──────────────────────
    // Well-known consent platform IDs and compound class selectors
    // that reliably identify consent dialogs.
    const highConfidenceSelectors = [
        '#onetrust-banner-sdk',
        '#qc-cmp2-ui',
        '#CybotCookiebotDialog',
        '#didomi-host',
        '#cmpbox',
        '#cookie-law-info-bar',
        '[class*="consent"][class*="banner"]',
        '[class*="consent"][class*="dialog"]',
        '[class*="cookie"][class*="banner"]',
        '[class*="cookie"][class*="dialog"]',
        '[class*="cmp"][class*="dialog"]',
        '[class*="privacy"][class*="banner"]',
    ];
    for (const sel of highConfidenceSelectors) {
        for (const el of document.querySelectorAll(sel)) {
            const bounds = getBounds(el);
            if (bounds) return bounds;
        }
    }

    // ── Broad selectors with keyword sniff ─────────────
    // These match elements that merely contain "consent", "cookie"
    // etc. in their class/id. To avoid grabbing non-consent
    // elements (e.g. a generic [role="dialog"]), require the
    // element's visible text to contain a consent-related keyword.
    const broadSelectors = [
        '[class*="consent"]',
        '[id*="consent"]',
        '[class*="cookie-banner"]',
        '[id*="cookie-banner"]',
        '[role="dialog"]',
    ];
    const consentKeywords = /cookie|consent|gdpr|privacy\s*polic|we\s+use|tracking|data\s+processing|legitimate\s+interest/i;
    for (const sel of broadSelectors) {
        for (const el of document.querySelectorAll(sel)) {
            const text = (el.innerText || '').trim();
            if (text.length > 10 && consentKeywords.test(text)) {
                const bounds = getBounds(el);
                if (bounds) return bounds;
            }
        }
    }

    return null;
})()
