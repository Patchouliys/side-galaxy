# Design

## Context

The existing homepage uses Canvas 2D for a fixed edge-on galaxy and SVG for its fallback. Navigation, workflow cards, and quickstart content already exist. See proposal.md for motivation.

## Goals / Non-Goals

**Goals:** Build a visually continuous, reversible transition using existing browser primitives. Keep text independent of the decorative canvas.

**Non-Goals:** Backend changes, real fleet telemetry in the illustration, new animation dependencies, and scroll interception.

## Decisions

- Use a native sticky scene inside a bounded scroll section. Derive a normalized progress from document geometry instead of intercepting wheel or touch input; direct anchors continue to work.
- Project a seeded particle galaxy and independently positioned device stars through a changing viewing angle. Cache the seeded galaxy in layered textures; only project those textures and independently move the six device stars during scroll transitions.
- Use a restrained teal, warm-white, and violet palette. Fade short narrative captions between stages, then let workflow cards enter the normal document flow.
- Keep the existing star-and-orbit SVG logo shared by the homepage and console.
- Schedule frames only while scroll interpolation is unsettled, using elapsed-time smoothing at the native display cadence. Stop canvas rendering when settled, hidden, or offscreen. Use small CSS opacity/scale overlays for subtle star glints and core breathing; pause these overlays when hidden, offscreen, or reduced motion is requested. A shared composited plane gently tilts the cached canvas and its glints together, up to two degrees either side of the scroll-driven angle; no idle canvas loop is needed. Retain a bounded pixel ratio and static readable reduced-motion/no-JavaScript layouts. Canvas 2D is sufficient; WebGL and animation libraries add unnecessary complexity.
- Reserve a final scroll hold of approximately 65% of the stage height on desktop and 40% on mobile. Keep the last light band and stars rigidly aligned during the gentle group tilt; remove board glyphs, clock-driven drift, and residual rotating rings.

- Restore the workflow to three parallel cards on desktop, with their diagrams below their descriptions; use one column on narrow screens.

## Risks / Trade-offs

- Long pinned scenes can obstruct navigation → keep direct anchors and shorten the sequence on small screens.
- Particle rendering can consume CPU → bake thousands of points once, project cached layers during transitions, and verify draw counts and frame callback timings in the same browser viewport.
- Faded text can become inaccessible → keep semantic text outside the canvas and ensure fallback layouts show essential content.
