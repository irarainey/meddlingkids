// Extract text from a consent iframe's body.
// Called via Playwright frame.evaluate() — must be a self-contained IIFE.
(() => {
    const t = document.body?.innerText?.trim();
    return t && t.length > 50 ? t : '';
})()
