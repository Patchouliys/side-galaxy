# Side Galaxy Visual Guide

Side Galaxy uses an edge-on galaxy as its metaphor: a bright management core and independently running boards form an observable experiment space.

The identity asset is `src/side_galaxy/static/icon.svg`, a native 64×64 vector. Intersecting ellipses represent the galactic disk and orbits, with a bright central core and an upper-right star as distinguishing features. The wordmark is lowercase `side galaxy`; the Chinese product name means "edge-on galaxy." `galaxy.svg` is the main edge-on disk illustration. All assets are original project SVGs, without externally hosted fonts, images, or telemetry.

## Console

`index.html`, `style.css`, and `app.js` serve `/console`. The palette uses deep-space gray-blue `#10171E`, panels `#151F28`, warm white `#E3EDF0`, and a muted teal accent `#A0D7C2`. Amber warnings and pale red errors are reserved for status and accompanied by text.

The console prioritizes bundle upload, target selection, arguments, preflight, execution, and results. Advanced resource options are collapsed; large illustrations and promotional slogans are omitted. System fonts support reading, while monospace is used for version hashes, code, and parameters. Artifact SHA-256 hashes, synthetic markers, and failure reasons remain available. Logs and outputs return after the task finishes; the interface does not pretend to stream live logs.

The layout consists of a narrow sidebar, compact statistics, a board list, and an experiment form. They sit side by side on desktop and stack on small screens; keyboard focus, readable labels, page-status announcements, and native dialogs remain accessible. The interface does not depend on an additional frontend framework.

## Promotional Homepage

`homepage.html`, `homepage.css`, and `homepage.js` serve `/`. Generous spacing, a teal core, and an edge-on disk introduce the product, while the console retains only the brand identity. Content covers the experiment workflow, modular architecture, Web / CLI / MCP, and local startup. Diagrams explain file and service relationships without showing invented measurements or device states.

Effects are limited to slow disk breathing, slight pointer parallax, and scroll-in reveals, implemented with native CSS and a little JavaScript, without canvas particles or external dependencies. `prefers-reduced-motion` disables all movement, and text remains readable without JavaScript. The homepage is labeled Preview and states that Pi / KVM hardware has not passed acceptance testing; it claims neither hardware isolation nor certification.

The homepage galaxy uses native Canvas 2D to draw a warm-white core, a cyan-blue and pale-violet dust disk, dark dust lanes, and orbital particles with trails, with slight pointer parallax. Static detail is cached, animation is capped at 30 fps, and DPR at 1.75; it pauses in the background and offscreen, and retains a static galaxy under reduced motion.
