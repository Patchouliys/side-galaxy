# Design

## Context

The existing homepage uses Canvas 2D for a fixed edge-on galaxy and SVG for its fallback. Navigation, workflow cards, and quickstart content already exist. See proposal.md for motivation.

## Goals / Non-Goals

**Goals:** Build a visually continuous, reversible transition using existing browser primitives. Keep text independent of the decorative canvas.

**Non-Goals:** Backend changes, real fleet telemetry in the illustration, physical galaxy simulation, new animation dependencies, and scroll interception.

## Decisions

- Use a native sticky scene inside a bounded scroll section. Derive a normalized progress from document geometry instead of intercepting wheel or touch input; direct anchors continue to work.
- Project a seeded particle galaxy and six device stars through a changing viewing angle. Start at a 0.78-radian tilt (approximately 45 degrees) with a -0.28-radian image-plane rotation. Give the stars distinct starting angles and normalized orbital radii of 0.62, 0.91, 1.16, 0.76, 1.28, and 0.98, avoiding an evenly spaced opening ring. Cache the seeded galaxy in layered textures. One JavaScript clock drives the six DOM stars with angular rates `1 / sqrt(r² + 0.32²)` and a 44-second base period, so their opening periods range from approximately 31 to 58 seconds. Three cached dust layers use that curve at radii 0.36, 0.69, and 1.02, producing periods of approximately 21 to 47 seconds; the underlying spiral pattern uses rate 0.61, or approximately 72 seconds per turn. This art-directed curve evokes differential rotation and a distinct spiral-pattern speed without claiming physical simulation. Apply the scroll-driven scale and viewing angle to the projected plane. Slow orbital motion over normalized scroll progress 0.43 through 0.90, and stop it before the final evenly spaced star line. Fade the spinning disk layers away before the final light band, without residual crossing rings.
- Use a restrained teal, warm-white, and violet palette. Fade short narrative captions between stages, then let workflow cards enter the normal document flow.
- Keep the existing star-and-orbit SVG logo shared by the homepage and console.
- Use elapsed-time smoothing at the native display cadence for scroll transitions. Redraw canvas pixels only while that transition changes; an active orbital clock may continue scheduling animation frames to update the cached layers and DOM stars without canvas redraws. Stop that loop when the final composition settles, or when hidden, offscreen, or reduced motion is requested. Use small CSS overlays for subtle glints and core breathing. All effects pause when hidden, offscreen, or reduced motion is requested; none needs an idle canvas redraw. Retain a bounded pixel ratio and static readable reduced-motion/no-JavaScript layouts. Canvas 2D is sufficient; WebGL and animation libraries add unnecessary complexity.
- Reserve a final scroll hold of approximately 65% of the stage height on desktop and 40% on mobile. Render the final scene as a slim edge-on galaxy with a luminous core and tapered dusty wings, rather than a uniform line. On desktop, use center coordinates `(0.73 * width, 0.50 * height)`, radius `0.25 * width`, and angle `-0.08` radians; retain the centered small-screen composition. Keep the final galaxy and evenly spaced device stars fixed, without group sway, independent drift, or residual rotating rings. Only faint opacity breathing remains at this stage.

- Restore the workflow to three parallel cards on desktop, with their diagrams below their descriptions; use one column on narrow screens.

## Risks / Trade-offs

- Long pinned scenes can obstruct navigation → keep direct anchors and shorten the sequence on small screens.
- Particle rendering can consume CPU → bake thousands of points once, project cached layers during transitions, and verify draw counts and frame callback timings in the same browser viewport.
- Layered transforms can produce heavy overlapping texture, clipping, or abrupt disappearance → separate the base pattern from sparse dust layers, fade them before convergence, and inspect both scroll directions and the fixed final composition on desktop and narrow screens.
- Independent timers can introduce discontinuities → derive all differential rates from one elapsed-time clock, pause it with visibility, and check the slowdown and reverse-scroll transition into and out of the final line.
- Faded text can become inaccessible → keep semantic text outside the canvas and ensure fallback layouts show essential content.
