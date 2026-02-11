// Extract text from consent-related DOM elements on the main page.
// Called via Playwright page.evaluate() — must be a self-contained IIFE.
(() => {
    const selectors = [
        '[class*="cookie"]',
        '[class*="consent"]',
        '[class*="privacy"]',
        '[class*="gdpr"]',
        '[id*="cookie"]',
        '[id*="consent"]',
        '[role="dialog"]',
        '[class*="modal"]',
        '[class*="banner"]',
        '[class*="overlay"]',
        '[class*="cmp"]',
        '[class*="tcf"]',
        '[class*="vendor"]',
        '[class*="partner"]',
    ];
    const elements = [];
    for (const sel of selectors) {
        document.querySelectorAll(sel).forEach(el => {
            const text = el.innerText?.trim();
            if (text && text.length > 10 && text.length < 15000) {
                elements.push(text);
            }
        });
    }
    document.querySelectorAll('table').forEach(table => {
        const text = table.innerText?.trim();
        if (
            text &&
            (text.toLowerCase().includes('partner') ||
                text.toLowerCase().includes('vendor') ||
                text.toLowerCase().includes('cookie') ||
                text.toLowerCase().includes('purpose'))
        ) {
            elements.push(text);
        }
    });
    document.querySelectorAll('ul, ol').forEach(list => {
        const text = list.innerText?.trim();
        const pt = list.parentElement?.innerText?.toLowerCase() || '';
        if (
            text &&
            text.length > 50 &&
            (pt.includes('partner') ||
                pt.includes('vendor') ||
                pt.includes('third part'))
        ) {
            elements.push('PARTNER LIST:\n' + text);
        }
    });
    return [...new Set(elements)].join('\n\n---\n\n');
})()
