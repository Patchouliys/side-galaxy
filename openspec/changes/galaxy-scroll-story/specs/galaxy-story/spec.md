# Spec Delta

## Purpose

Explain how independent boards become one managed experiment workflow through an accessible, scroll-driven Side Galaxy visual narrative.

## ADDED Requirements

### Requirement: Reversible galaxy convergence
The homepage SHALL progress from a face-on nebula with device stars to an edge-on light band with converged device stars as the visitor scrolls, and SHALL reverse that progression when scrolling upward.

#### Scenario: Traverse the story
- **WHEN** a visitor scrolls through the homepage opening
- **THEN** the nebula tilts, device stars migrate toward the unified band, and the upload, execution, and results steps progressively appear afterward

#### Scenario: Return to the opening
- **WHEN** the visitor scrolls back to the top
- **THEN** the face-on nebula and scattered device stars return

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
The scene SHALL represent devices with bright star points instead of board glyphs. After convergence, the light band and star positions SHALL remain fixed relative to one another during gentle group rotation while a reserved scroll interval precedes the workflow section.

#### Scenario: Completed convergence
- **WHEN** the visitor reaches the final animation phase and pauses or continues within the final hold interval
- **THEN** no residual orbit rotates across the light band, and the completed composition remains visible before the workflow enters

### Requirement: Rendering stops when the scene settles
The main galaxy canvas SHALL stop scheduling animation frames when its scroll transition has settled, or when it is hidden or offscreen. Scrolling SHALL resume a smooth reversible transition without regenerating static galaxy detail every frame.

#### Scenario: Idle scene
- **WHEN** the visitor stops scrolling and interpolation reaches the requested position
- **THEN** no recurring canvas render loop continues; composited decorative effects and gentle whole-band rotation may continue without changing the relative positions of the band and device stars

#### Scenario: Resume scrolling
- **WHEN** the visitor scrolls again
- **THEN** rendering resumes for the transition while retaining the cached galaxy detail


### Requirement: Restrained ambient depth
The homepage SHALL provide subtle star glints and core breathing with gentle synchronized rotation of the final light band and device stars. These decorative effects SHALL stop when the page is hidden, the scene is offscreen, or reduced motion is requested.

#### Scenario: Gentle motion at rest
- **WHEN** the visitor pauses on a visible scene with motion enabled
- **THEN** star brightness and core glow change subtly while the light band and stars tilt gently together without crossing or separating

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
