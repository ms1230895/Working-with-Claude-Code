// main.js — loaded on every page, after the Lucide script in base.html

// Turn every <i data-lucide="name"> into its SVG icon. Skipped when the
// Lucide script did not load (offline, or the CDN is blocked), so the page
// still works without icons
if (window.lucide) {
    window.lucide.createIcons();
}
