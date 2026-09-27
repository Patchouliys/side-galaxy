# Tasks

## 1. Identity

- [x] 1.1 Restore the original shared SVG logo and keep the brand guide consistent; verify valid SVG and readable navigation-size rendering.

## 2. Scroll narrative

- [x] 2.1 Implement the opening, tilt, convergence, and workflow reveal sequence; verify JavaScript syntax and browser checkpoints in both scroll directions.
- [x] 2.2 Preserve direct navigation and static fallbacks, and describe the animation in the brand guide; verify keyboard navigation, narrow layout, and reduced-motion/no-script behavior.

## 3. Integration

- [x] 3.1 Validate the OpenSpec change and inspect the complete homepage with the shared logo; verify repository checks and review the publishable diff for local information.


## 4. Performance and final composition

- [x] 4.1 Cache static galaxy layers and use demand-driven rendering; verify fewer draw calls and compare browser callback timings against the saved baseline at the same viewport, plus idle/offscreen/reduced-motion lifecycle checks.
- [x] 4.2 Replace board glyphs with bright star points and remove independent orbital movement after convergence; verify the final light band and labels retain their relative positions.
- [x] 4.3 Add a final scroll hold and update the brand guide; verify final convergence precedes sticky release on desktop and mobile without intercepting scrolling.

- [x] 4.4 Add restrained composited star glints and core breathing; visually verify subtle depth, rigid final geometry, and paused effects offscreen or with reduced motion.


## 5. Workflow layout and ambient motion

- [x] 5.1 Restore the three-column desktop workflow and narrow-screen stacking; verify browser geometry, readability, and no horizontal overflow.
- [x] 5.2 Add visible cached-disk rotation without idle canvas rendering; verify the disk turn, fade before final convergence, and pause behavior for hidden/offscreen/reduced-motion states.

## 6. Oblique opening and differential rotation

- [x] 6.1 Start with an oblique nebula and six stars at unequal angles and radii; use one clock with radius-dependent star/dust rates and a distinct spiral-pattern rate, then converge into a fixed slim galaxy with a luminous core, tapered dusty wings, and evenly spaced stars at the desktop scene's right-center. Verify visible differential rotation, reverse-scroll continuity, no final sway or orbital frame loop, zero settled canvas redraws, and hidden/offscreen/reduced-motion pause behavior; document the artistic simplification with primary references.
