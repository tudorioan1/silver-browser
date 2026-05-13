# silver-browser

A PyQt6 desktop web browser built on Qt WebEngine/Chromium with privacy-first defaults.
Privacy features included:

- strict request interceptor for common ads, trackers, social widgets, cryptominers, and fingerprinting scripts
- HTTPS-only request upgrades where possible
- Do Not Track and Global Privacy Control headers
- private off-the-record windows
- session-only cookies/cache by default
- third-party cookie blocking through Chromium startup flags
- canvas/WebGL/WebRTC fingerprinting resistance settings
- permission prompts for location, camera, microphone, notifications, clipboard, screen capture, and local fonts
- clear history, cookies, cache, and visited-link data
- built-in info page at `browser://info`, made by Tudor Ioan, `tudorioan1` on GitHub
- built-in search settings page at `browser://settings` for choosing Google or DuckDuckGo

Browser features included:

- tabs, new-window handling, address/search bar, back/forward/reload/home
- bookmarks and recent history
- downloads with save prompts
- find-in-page, zoom controls, PDF printing, page save, and developer tools
- dark mode included
