# Spec Delta

## Purpose

Explain how independent boards become one managed experiment workflow through an accessible, scroll-driven Side Galaxy visual narrative.

## ADDED Requirements

### Requirement: Reversible galaxy convergence
The homepage SHALL progress from an oblique nebula with device stars to a slim edge-on galaxy with a luminous core, tapered dust wings, and converged device stars as the visitor scrolls, and SHALL reverse that progression when scrolling upward.

#### Scenario: Traverse the story
- **WHEN** a visitor scrolls through the homepage opening
- **THEN** the nebula tilts, device stars migrate toward the unified band, and the upload, execution, and results steps progressively appear afterward

#### Scenario: Return to the opening
- **WHEN** the visitor scrolls back to the top
- **THEN** the oblique nebula and unevenly distributed device stars return

### Requirement: Differential orbital motion
The six device stars SHALL begin at distinct angles and radii and orbit in the same direction at radius-dependent angular speeds. Cached dust layers SHALL also use different angular rates, while the spiral pattern SHALL have its own rate. All rates SHALL derive from one animation clock, with inner stars completing orbits sooner than outer stars. This SHALL be presented as an artistic simplification rather than a physical simulation. Orbital motion SHALL slow during convergence and stop before the final line. Only the final star line SHALL use even spacing.

#### Scenario: Orbit before convergence
- **WHEN** the opening scene is visible with motion enabled
- **THEN** inner stars and dust layers advance through their orbits faster than outer ones, while the spiral pattern remains visually distinct and all elements retain the same projected plane

#### Scenario: Settle into the final line
- **WHEN** scrolling converges the scene toward its final phase
- **THEN** orbital motion slows to a stop and the six stars settle into an evenly spaced line with no remaining independent orbital movement

### Requirement: Accessible direct navigation
The homepage SHALL retain ordinary scrolling and direct workflow and console links. Essential content SHALL remain readable without JavaScript and when reduced motion is requested, including on narrow screens.

#### Scenario: Skip the animation
- **WHEN** a visitor activates the workflow link with the keyboard
- **THEN** the workflow section becomes directly accessible without traversing each visual phase

#### Scenario: Reduced motion or unavailable script
- **WHEN** JavaScript is unavailable or the visitor requests reduced motion
- **THEN** the page presents a readable static composition with all workflow steps available

### Requirement: Consistent vector identity
The homepage and console SHALL use the original shared star-and-orbit logo that remains recognizable at navigation and favicon sizes.

#### Scenario: Logo at different sizes
- **WHEN** the logo is displayed in a navigation bar or as a small icon
- **THEN** its orbit silhouette and bright central star remain distinguishable


### Requirement: Stable star convergence and final hold
The scene SHALL represent devices with bright star points instead of board glyphs. After convergence, the galaxy and evenly spaced stars SHALL remain fixed in the scene without group sway or residual orbital motion while a reserved scroll interval precedes the workflow section. The final galaxy SHALL occupy the right-center on desktop and remain centered on narrow screens.

#### Scenario: Completed convergence
- **WHEN** the visitor reaches the final animation phase and pauses or continues within the final hold interval
- **THEN** the luminous core, tapered wings, and device stars stay in place without residual orbits, and the completed composition remains visible before the workflow enters

### Requirement: Canvas redraws stop when the scroll transition settles
The galaxy canvases SHALL stop redrawing pixels when the scroll transition has settled, or when the scene is hidden or offscreen. Before convergence, animation frames MAY continue updating the shared orbital clock and DOM/CSS transforms without canvas redraws. At the settled final phase, the scene SHALL stop scheduling animation frames. Scrolling SHALL resume a smooth reversible transition without regenerating static galaxy detail every frame.

#### Scenario: Idle scene
- **WHEN** the visitor stops scrolling and interpolation reaches the requested position
- **THEN** no recurring canvas redraw continues; a shared orbital loop may update cached disk and star transforms before convergence, while the completed galaxy remains fixed with only faint opacity breathing

#### Scenario: Final scene at rest
- **WHEN** scroll interpolation settles at the completed final line
- **THEN** no orbital animation-frame loop continues and no idle transform moves the final composition; faint composited opacity breathing may remain active

#### Scenario: Resume scrolling
- **WHEN** the visitor scrolls again
- **THEN** rendering resumes for the transition while retaining the cached galaxy detail


### Requirement: Restrained ambient depth
The homepage SHALL provide visibly rotating cached disk detail before convergence and subtle star glints and core breathing. The rotating disk SHALL fade out before final convergence; only faint opacity breathing SHALL remain in the fixed final composition. These decorative effects SHALL use composited transforms or opacity without idle canvas redraws, and SHALL stop when the page is hidden, the scene is offscreen, or reduced motion is requested.

#### Scenario: Visible disk rotation
- **WHEN** the visitor pauses on the opening or tilted galaxy with motion enabled
- **THEN** the cached disk layers and device stars visibly rotate at distinct rates within their projected plane, and scrolling toward convergence slows their orbital motion and fades the disk without leaving a crossing ring

#### Scenario: Gentle motion at rest
- **WHEN** the visitor pauses on a visible scene with motion enabled
- **THEN** star brightness and core glow change subtly; in the final phase the galaxy and device stars stay fixed without crossing, swaying, or clipping essential content

#### Scenario: Ambient effects disabled
- **WHEN** reduced motion is requested or the scene is no longer visible
- **THEN** recurring ambient effects are disabled or paused


### Requirement: Parallel workflow cards
The homepage SHALL display the upload, execution, and results steps as three side-by-side cards on desktop, preserving their order in a single column on narrow screens.

#### Scenario: Desktop workflow
- **WHEN** the homepage is viewed on a desktop viewport
- **THEN** all three workflow steps occupy the same row with diagrams beneath their text

#### Scenario: Narrow workflow
- **WHEN** the viewport is too narrow for three readable cards
- **THEN** the steps stack in their original order without horizontal overflow
