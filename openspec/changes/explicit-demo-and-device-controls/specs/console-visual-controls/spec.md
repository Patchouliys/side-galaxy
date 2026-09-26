# Spec Delta

## Purpose

Expose laboratory modes and lifecycle actions with clear hierarchy and a restrained galaxy visual identity.

## ADDED Requirements

### Requirement: Mode and action clarity
The console SHALL display the current mode, provide a working demo switch, distinguish graceful reload from forced reload, and show restart controls only for managed QEMU devices. Interruptive actions SHALL identify their target and require confirmation.

#### Scenario: Busy device controls
- **WHEN** an operator inspects a busy managed device
- **THEN** force reload and QEMU restart explain interruption and show pending or failed state without duplicate submissions

### Requirement: Usable visual styling
The console SHALL retain readable device/resource tables and focused forms while adding restrained galaxy accents and subtle motion. It SHALL respect reduced motion and remain usable on desktop and narrow screens.

#### Scenario: Reduced motion
- **WHEN** reduced motion is requested
- **THEN** nonessential ambient and transition effects are disabled
