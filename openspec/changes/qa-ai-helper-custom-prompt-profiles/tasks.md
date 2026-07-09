# Tasks: Cancelled Custom Prompt Profiles

- [x] Remove prompt profile router registration.
- [x] Remove prompt profile fields from active QA AI Helper request/response models.
- [x] Stop resolving defaults, injecting style guidance, writing snapshots, or emitting profile telemetry.
- [x] Remove QA AI Helper custom style controls and frontend endpoint calls.
- [x] Remove `qaAiHelper.promptProfiles.*` locale blocks.
- [x] Update tests to assert retired endpoint behavior and ignored legacy `prompt_profile_id` inputs.
- [x] Update main OpenSpec contract to document the retired capability.
- [ ] Destructive schema cleanup is intentionally not done; dropping legacy tables/columns requires explicit approval.
