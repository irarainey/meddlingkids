// Return the bounding rectangle of the first visible consent dialog container.
// Called via Playwright page.evaluate() — must be a self-contained IIFE.
// Returns {left, top, right, bottom} or null if no container is found.
(() => {
    const selectors = [
        '#onetrust-banner-sdk',
        '#qc-cmp2-ui',
        '#CybotCookiebotDialog',
        '#didomi-host',
        '#cmpbox',
        '#cookie-law-info-bar',
        '[role="dialog"]',
        '[class*="consent"][class*="banner"]',
        '[class*="consent"][class*="dialog"]',
        '[class*="cookie"][class*="banner"]',
        '[class*="cookie"][class*="dialog"]',
        '[class*="cmp"][class*="dialog"]',
        '[class*="privacy"][class*="banner"]',
    ];
    for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
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
        }
    }
    return null;
})()
