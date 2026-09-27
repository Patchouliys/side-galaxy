# Proposal

## Why

The homepage currently shows a fixed edge-on galaxy without explaining how independent devices become a managed fleet. A scroll-led visual sequence can connect the Side Galaxy identity to the experiment workflow.

## What Changes

- Preserve the original shared star-and-orbit logo.
- Start the homepage with a face-on nebula surrounded by device stars, then tilt and converge them into one managed light band as the visitor scrolls.
- Represent devices as bright stars, hold the completed stable light band briefly during scrolling, and then reveal the upload, execution, and results steps.
- Cache galaxy detail and redraw it only while scroll transitions change, removing idle rotation and overlapping orbital effects. Add restrained composited star glints and a soft core breath with a small synchronized tilt of the completed band and stars.
- Preserve natural scrolling, skip links, reduced-motion readability, and a useful no-JavaScript fallback.

- Present the three experiment workflow steps side by side on desktop and stack them on narrow screens.

## Capabilities

### New Capabilities

- `galaxy-story`: Scroll-driven brand storytelling and accessible workflow entry.

### Modified Capabilities

None.

## Impact

Homepage HTML, CSS, Canvas 2D animation, SVG identity assets, and the brand guide. No API, execution, database, or dependency changes.
