// Extract text from consent-related DOM elements on the main page.
// Called via Playwright page.evaluate() — must be a self-contained IIFE.
//
// IMPORTANT: selectors are intentionally narrow to avoid pulling in
// non-consent text (news headlines, navigation, ads) from the page.
// Broad selectors like [class*="banner"] or [role="dialog"] are only
// used as fallbacks with a text-content sniff.
(() => {
    // High-confidence consent-specific selectors.
    const consentSelectors = [
        '[class*="cookie"][class*="consent"]',
        '[class*="cookie"][class*="banner"]',
        '[class*="cookie"][class*="dialog"]',
        '[class*="cookie"][class*="notice"]',
        '[class*="consent"][class*="banner"]',
        '[class*="consent"][class*="dialog"]',
        '[class*="consent"][class*="notice"]',
        '[class*="privacy"][class*="banner"]',
        '[class*="privacy"][class*="notice"]',
        '[class*="gdpr"]',
        '[class*="cmp"][class*="dialog"]',
        '[class*="cmp"][class*="banner"]',
        '[class*="cmp"][class*="container"]',
        '[class*="tcf"]',
        '[id*="cookie"][id*="consent"]',
        '[id*="cookie"][id*="banner"]',
        '[id*="cookie"][id*="notice"]',
        '#onetrust-banner-sdk',
        '#qc-cmp2-ui',
        '#CybotCookiebotDialog',
        '#didomi-host',
        '#cmpbox',
        '#cookie-law-info-bar',
    ];
    const elements = [];
    const seen = new Set();
    const addText = (text) => {
        if (text && text.length > 10 && text.length < 15000 && !seen.has(text)) {
            seen.add(text);
            elements.push(text);
        }
    };
    for (const sel of consentSelectors) {
        document.querySelectorAll(sel).forEach(el => {
            addText(el.innerText?.trim());
        });
    }
    // Broader selectors — only include if the element's text
    // contains consent-related keywords.
    const broadSelectors = [
        '[id*="cookie"]',
        '[id*="consent"]',
        '[class*="cookie"]',
        '[class*="consent"]',
        '[class*="privacy"]',
        '[role="dialog"]',
        '[class*="banner"]',
        '[class*="overlay"]',
        '[class*="modal"]',
        '[class*="vendor"]',
        '[class*="partner"]',
    ];
    const consentKeywords = /cookie|consent|gdpr|privacy\s*polic|we\s+use|tracking|data\s+processing|legitimate\s+interest/i;
    for (const sel of broadSelectors) {
        document.querySelectorAll(sel).forEach(el => {
            const text = el.innerText?.trim();
            if (text && text.length > 10 && text.length < 15000 && consentKeywords.test(text)) {
                addText(text);
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
            addText(text);
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
            addText('PARTNER LIST:\n' + text);
        }
    });
    return elements.join('\n\n---\n\n');
})()
