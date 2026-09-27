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

The opening views the nebula obliquely at approximately 45°, with six device stars at different radii and angles orbiting in the same direction at different speeds. Inner stars complete their orbits sooner than outer stars. As the visitor scrolls down, the disk tilts further, orbital motion slows, and the devices converge into a slim edge-on galaxy with a luminous core and tapered dust wings. The device stars become evenly spaced only in the final composition. A reserved scroll hold precedes the three steps: upload code, select targets and execute, and view results. Scrolling upward reverses the sequence, and navigation can skip the animation.

The galaxy uses native Canvas 2D to cache nebula detail, represents devices as brighter DOM stars, and keeps copy in ordinary HTML. A warm-white core, teal dust, and pale violet edges echo the logo. One JavaScript clock drives different angular rates: the six device stars use `1 / sqrt(r² + 0.32²)` with a 44-second base period, producing opening periods of approximately 31–58 seconds. Three cached dust layers use the same curve at normalized radii 0.36, 0.69, and 1.02, producing periods of approximately 21–47 seconds. The underlying spiral pattern uses a separate rate of 0.61, or approximately 72 seconds per turn. Motion slows between 43% and 90% scroll progress, and the disk fades out before final convergence.

These rates are an art-directed simplification, not a physical simulation. The visual distinction draws on [ESA Gaia's explanation of differential rotation](https://www.cosmos.esa.int/web/gaia/dr3-where-do-the-stars-go-or-come-from), where inner stars complete orbits sooner than outer stars, and [NASA's account of spiral density patterns](https://science.nasa.gov/missions/hubble/hubble-spies-galactic-traffic-jam/), through which disk material moves rather than remaining attached to a rigid arm.

Canvas draws at the browser's frame cadence only during scroll transitions and does not redraw once scrolling settles. While orbital motion remains active, animation frames only update cached-layer and DOM-star transforms; orbital animation frames stop once the final composition settles.

A separate starlight layer provides subtle glints and core breathing. The final galaxy stays fixed in the right-center of the desktop scene, centered at 73% of its width and 50% of its height, with a radius of 25% of its width and a slight -0.08-radian tilt. Small screens retain a centered composition. The core, tapered wings, and evenly spaced stars do not sway or continue orbiting; only a faint opacity breath remains. Motion and glow effects pause in the background, offscreen, and under reduced motion. DPR is capped at 1.6; small screens use a shorter scroll sequence, `prefers-reduced-motion` uses a static layout, and text, steps, and SVG visuals remain available without JavaScript.
