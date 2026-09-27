# Proposal

## Why

The homepage currently shows a fixed edge-on galaxy without explaining how independent devices become a managed fleet. A scroll-led visual sequence can connect the Side Galaxy identity to the experiment workflow.

## What Changes

- Preserve the original shared star-and-orbit logo.
- Start the homepage with an oblique nebula and six unevenly distributed device stars orbiting at radius-dependent speeds, then tilt and converge them into a slim edge-on galaxy as the visitor scrolls.
- Represent devices as bright stars, hold the completed fixed galaxy briefly during scrolling, and then reveal the upload, execution, and results steps.
- Cache galaxy detail and redraw it only while scroll transitions change. Drive the spiral pattern, dust layers, and six DOM stars from one clock with distinct angular rates, slow that motion during convergence, and fade the rotating disk before the final evenly spaced star line. Place the final luminous core and tapered dust wings at the desktop scene's right-center, with only faint opacity breathing and no sway or residual orbits.
- Preserve natural scrolling, skip links, reduced-motion readability, and a useful no-JavaScript fallback.

- Present the three experiment workflow steps side by side on desktop and stack them on narrow screens.

## Capabilities

### New Capabilities

- `galaxy-story`: Scroll-driven brand storytelling and accessible workflow entry.

### Modified Capabilities

None.

## Impact

Homepage HTML, CSS, Canvas 2D animation, SVG identity assets, and the brand guide. No API, execution, database, or dependency changes.
