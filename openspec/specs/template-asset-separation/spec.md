# Capability: Template Asset Separation

## Purpose

Separate inline CSS and JavaScript from templates into external static assets for better maintainability and caching. This refactor focuses on remaining in-scope templates while preserving load order and behavior.

## Requirements

### Requirement: Remaining templates use external assets
The system SHALL move inline CSS and JS from the remaining in-scope templates into external static assets under `app/static/css` and `app/static/js`.

#### Scenario: Page loads after refactor
- **WHEN** a refactored template is rendered
- **THEN** its CSS and JS SHALL be loaded from external files rather than inline blocks

### Requirement: Preserve load order and behavior
The system SHALL preserve the existing script load order and global symbols so UI and behavior remain unchanged.

#### Scenario: Existing behavior intact
- **WHEN** a user interacts with a refactored page
- **THEN** the UI behavior and functionality SHALL match the pre-refactor behavior

### Requirement: Shared templates are excluded
The system SHALL leave shared templates (e.g., `base.html`, `_partials/`, `components/`) unchanged in this refactor.

#### Scenario: Shared templates unchanged
- **WHEN** the refactor is applied
- **THEN** shared template files SHALL remain untouched
