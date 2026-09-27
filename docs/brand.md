# Side Galaxy Visual Guide

Side Galaxy uses an edge-on galaxy as its metaphor: a bright management core and independently running boards form an observable experiment space. The wordmark is lowercase `side galaxy`; the Chinese product name means "edge-on galaxy."

## Identity and Colors

The identity asset is `src/side_galaxy/static/icon.svg`, a native 64×64 vector. Intersecting ellipses represent the galactic disk and orbits, with a bright central core and an upper-right star as distinguishing features; `galaxy.svg` provides a static disk illustration. The interface uses system fonts without externally hosted fonts or images.

| Purpose | Color |
|---|---|
| Console background | `#10171E` |
| Panels | `#151F28` |
| Body text | `#E3EDF0` |
| Accent | `#A0D7C2` |

Amber warnings and pale red errors indicate status, accompanied by text. Monospace fonts are used for code, parameters, versions, and content hashes.

## Console

`index.html`, `style.css`, and `app.js` serve `/console`. A narrow sidebar, compact statistics, a board list, and an experiment form make up the workspace; they sit side by side on desktop and stack on small screens.

The main workflow is organized around uploading a bundle, selecting targets, configuring parameters, preflight, execution, and results. Advanced resource options are collapsed, while artifact SHA-256 hashes, synthetic markers, and failure reasons remain available. Logs and outputs return after a task finishes.

Keep keyboard focus, readable labels, status announcements, and native dialogs accessible; decoration should not occupy the primary work area.

## Homepage

`homepage.html`, `homepage.css`, and `homepage.js` serve `/`. Content covers the experiment workflow, modular architecture, Web / CLI / MCP, and local startup. The three experiment steps appear in parallel columns on desktop and stack in their original order on small screens.

The opening shows a face-on nebula and scattered device stars. As the visitor scrolls down, the disk tilts and each device follows its own path into a unified light band. The final composition has a reserved scroll hold before the three steps appear: upload code, select targets and execute, and view results. Scrolling upward reverses the sequence, and navigation can skip the animation.

The galaxy uses native Canvas 2D to cache nebula detail, represents devices as brighter independent star points, and keeps copy in ordinary HTML. A warm-white core, teal dust, and pale violet edges echo the logo; the nebula canvas draws at the browser's frame cadence only during scroll transitions and does not redraw at rest. A separate starlight layer uses slight opacity and scale changes for glints and core breathing, pausing in the background, offscreen, and under reduced motion. DPR is capped at 1.6. After convergence, the band, stars, and glow retain their relative positions and sway slowly together through ±2°, without independent crossing orbits. Small screens use a shorter scroll sequence, `prefers-reduced-motion` uses a static layout, and text, steps, and SVG visuals remain available without JavaScript.
