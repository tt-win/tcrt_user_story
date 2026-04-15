## ADDED Requirements

### Requirement: Multi-set section hydration for execution page
The system SHALL load section trees from all Test Case Sets configured on a Test Run and merge them for execution filtering/grouping.

#### Scenario: Execution page loads sections from multiple sets
- **WHEN** a Test Run configuration contains multiple Test Case Set IDs
- **THEN** the execution page fetches sections for each configured set
- **AND** merged section filters are available before item rendering completes

### Requirement: Execution filtering remains stable with multi-set items
The system SHALL preserve existing execution filter behaviors when Test Run items span multiple Test Case Sets.

#### Scenario: Filter and group multi-set execution items
- **WHEN** execution items belong to different Test Case Sets
- **THEN** section grouping, section checkbox filters, and existing non-section filters continue to work without runtime errors

#### Scenario: Reflect backend cleanup results
- **WHEN** backend cleanup removes out-of-scope Test Run items
- **THEN** execution page reload shows the updated item list without deleted items
- **AND** section/filter rendering remains consistent
