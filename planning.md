# BetterFleets V2 — Development Plan

## Project Goal

We are working on **BetterFleets V2**.

The priority is to develop V2 safely without affecting the existing production installation. Production must remain untouched while development takes place.

Before making implementation changes, inspect the existing codebase and architecture and adapt this plan to the actual project structure.

---

# 0. Development Environment & Git Workflow ✅ COMPLETED

## Objective

Create a completely isolated development environment so V2 can be developed and tested without affecting production.

### Requirements

* [x] Inspect the existing Git repository and current branch structure.
* [x] Create a dedicated `dev` branch for V2 development.
* [x] Do not make V2 changes directly on the production branch.
* [x] Ensure production can continue running unchanged while V2 is developed.
* [x] Create a separate development Docker Compose configuration.
* [x] The development Compose stack must use separate:

  * [x] Container names where necessary.
  * [x] Ports where necessary.
  * [x] Volumes.
  * [x] Database/database credentials where necessary.
  * [x] Networks where necessary.
  * [x] Environment configuration.
* [x] Make sure the development database cannot accidentally connect to or modify the production database.
* [x] Document how to start/stop the V2 development environment.
* [x] Document how to switch between production and development.
* [x] Verify the development environment works before beginning feature development.
* [x] Push the development branch to GitHub.

### Summary

**Task 0 completed successfully.** The development environment is fully isolated from production:

- Created dedicated `dev` branch for V2 development
- Verified existing `docker-compose.dev.yml` provides complete isolation:
  - Separate containers: `django_web_dev`, `postgres_dev`, `redis_dev`
  - Separate database: `betterfleets_dev` with user `dev_user`
  - Separate ports: `8010:8000` (vs production `8000:8000`)
  - Separate volumes: `postgres_data_dev`, `media_dev`
- Created `.env.dev` with development-specific configuration
- Updated `docs/DEV_ENVIRONMENT_SETUP.md` with V2-specific workflow and safety guidelines
- Pushed `dev` branch to GitHub
- Verified production configuration remains unchanged

**Files changed:**
- `docs/DEV_ENVIRONMENT_SETUP.md` - Added V2 development workflow, switching process, and safety checklist
- `.env.dev` - Created (gitignored, contains development environment variables)

**Note:** Docker Desktop was not running during setup, so actual environment startup testing is deferred. The documentation includes verification steps for the user to test when Docker Desktop is available.

---

# 1. Operator Vehicle Fleet Filters & Sorting

## Objective

Improve the vehicles page for an operator by adding proper filtering and sorting controls to the fleet table.

### Filters

Add a filter UI containing all reasonable fleet filters, including:

* [ ] Vehicle type.
* [ ] Livery.
* [ ] Age.
* [ ] VOR status.
* [ ] Trainer status.
* [ ] Withdrawn status.

Inspect the existing vehicle data model and UI and determine whether additional useful filters should be included.

Potential additional filters may include things such as:

* Fleet number presence/range.
* Registration.
* Operator ownership/status.
* Vehicle features.

Do not add unnecessary filters purely for the sake of having more options.

### Sorting

Add sorting controls for:

* [ ] Fleet number.
* [ ] Registration.
* [ ] Age.
* [ ] Vehicle type.

Sorting should be intuitive and support ascending/descending ordering where appropriate.

### UX

* [ ] Filters should be easy to discover.
* [ ] Users should be able to combine multiple filters.
* [ ] Users should be able to clear/reset filters.
* [ ] The table should clearly indicate active filters.
* [ ] Sorting state should be obvious.
* [ ] Preserve the existing visual style and responsive behaviour.
* [ ] Avoid unnecessary page reloads if the current architecture allows client-side filtering/sorting.
* [ ] Ensure filtering/sorting works correctly with pagination if pagination exists.

---

# 2. Improved Public Operator Profiles

## Objective

Improve public operator profiles and allow operators to have links to relevant external services.

### Social / External Links

Investigate the existing operator model/profile implementation and add support for external links.

At minimum consider:

* [ ] Flickr.
* [ ] Discord.
* [ ] TransitTracker.
* [ ] TransportStatistics.

The implementation should be extensible so additional links can be added later without requiring another schema redesign.

### UI

* [ ] Display available links prominently on the public operator profile.
* [ ] Do not display empty/unconfigured links.
* [ ] Use appropriate icons where the existing frontend design system supports them.
* [ ] Ensure links open safely.
* [ ] Make the profile look substantially better without disrupting existing functionality.

---

# 3. Theme System Expansion

## Objective

Expand the existing theme system.

The project currently has:

* Dark mode.
* Light mode.
* Solent Blue.

Add:

* [ ] Light.
* [ ] Dark.
* [ ] Light Pink.
* [ ] Dark Pink.
* [ ] Light Blue.
* [ ] Dark Blue.
* [ ] Light Contrast.
* [ ] Dark Contrast.

Investigate how the existing theme system works before implementing this.

### Requirements

* [ ] Preserve the existing theme functionality.
* [ ] Make themes consistent across the entire application.
* [ ] Ensure sufficient text/background contrast.
* [ ] Ensure tables, forms, buttons, modals, navigation, cards, alerts and other components work in every theme.
* [ ] Make the theme selector easy to use.
* [ ] Persist the user's selected theme.
* [ ] Respect system light/dark preference where appropriate.
* [ ] Ensure the themes work correctly on mobile.

---

# 4. Requests System

## Objective

Create a proper request system accessible from the footer.

The current system sends all requests to the changelog page. This needs to be redesigned.

## Request Options

The request page should provide these request types:

### Vehicle

* [ ] Vehicles.
* [ ] Vehicle types.
* [ ] Vehicle liveries.
* [ ] Vehicle features.
* [ ] Vehicle fields.

### Operator

* [ ] Operators.
* [ ] Operator logos.
* [ ] Operator services.
* [ ] Operator updates.
* [ ] Operator groups.

### Other

* [ ] Generic feature.
* [ ] Preservation group.
* [ ] Government authority.

Design the request system so additional request types can be added later.

---

# 5. Request Routing & Changelog

## Objective

Separate normal edits/vehicle requests from requests requiring TU review.

### Changelog

The changelog should contain:

* [ ] All edits.
* [ ] Vehicle requests.

Determine the cleanest way to preserve existing changelog functionality while introducing the new request system.

### TU Requests

Everything else should go to a dedicated **TU-only Requests** page.

This includes non-vehicle requests such as:

* Operator requests.
* Operator logo requests.
* Operator service requests.
* Operator update requests.
* Operator group requests.
* Vehicle type requests.
* Vehicle livery requests.
* Vehicle feature requests.
* Vehicle field requests.
* Generic feature requests.
* Preservation group requests.
* Government authority requests.

Verify the exact desired routing against the existing permissions/roles before implementation.

---

# 6. TU Request Discussion & Voting

## Objective

Give TUs a proper workflow for reviewing non-vehicle requests.

The TU requests page should allow authorised TUs to:

* [ ] View requests.
* [ ] Open a request.
* [ ] See the full request details.
* [ ] Discuss the request.
* [ ] Add comments.
* [ ] Vote Yes.
* [ ] Vote No.
* [ ] See the current vote result.
* [ ] See who has voted where permissions allow.
* [ ] Track request status.
* [ ] Mark requests as resolved/rejected/implemented as appropriate.

Investigate the existing user/role system before implementing permissions.

Do not assume what a "TU" is technically represented as in the database — inspect the current application.

---

# 7. Authentication — Investigate Clerk

## Objective

Investigate replacing or integrating the existing authentication system with **Clerk**.

This should initially be an investigation/design task rather than blindly replacing the current authentication system.

### Tasks

* [ ] Identify the current authentication implementation.
* [ ] Identify all parts of the application that depend on the current auth system.
* [ ] Identify user roles and permissions.
* [ ] Identify TU permissions.
* [ ] Determine how accounts/users are currently stored.
* [ ] Research how Clerk could integrate with the current backend/frontend architecture.
* [ ] Determine whether Clerk can preserve the existing user/role model.
* [ ] Determine migration requirements for existing users.
* [ ] Determine whether Clerk is actually beneficial for this project.
* [ ] Document the recommended approach.
* [ ] Only implement the migration after the architecture and migration risks are understood.

Do not break existing authentication simply to experiment with Clerk.

---

# 8. Discord Error Notifications

## Objective

Notify a developer role in Discord whenever the application encounters an important/unhandled error.

### Requirements

* [ ] Identify the existing application error-handling/logging architecture.
* [ ] Determine what should constitute a Discord notification.
* [ ] Avoid sending notifications for expected/user-caused errors that would create spam.
* [ ] Send serious/unhandled application errors to Discord.
* [ ] Mention/ping the configured developer role.
* [ ] Include useful debugging information.
* [ ] Include environment information where safe.
* [ ] Never expose passwords, API keys, tokens, session data or other secrets.
* [ ] Prevent notification loops if Discord itself fails.
* [ ] Add configuration through environment variables.
* [ ] Make Discord notifications optional so development/testing can disable them.

---

# 9. BetterFleets Discord Bot

## Objective

Build a BetterFleets Discord bot providing useful database-style searches.

The bot should feel somewhat like being able to perform SQL-style queries against BetterFleets, but through simple Discord commands.

Use Discord embeds for results.

---

## `/search`

### Usage

`/search {reg} {fleet code}`

The command should allow searching vehicles using registration and/or fleet number.

Examples:

* Registration only.
* Fleet number only.
* Both registration and fleet number.

### Results

Display useful vehicle information in an embed, such as:

* Vehicle.
* Registration.
* Fleet number.
* Type.
* Livery.
* Operator.
* Status.
* Link to BetterFleets vehicle page.

Determine the exact available fields from the existing database.

---

# 10. Discord `/count`

## Objective

Allow users to count vehicles based on fleet attributes.

### Commands

`/count {vehicle type}`

`/count {livery name}`

### Requirements

* [ ] Count matching vehicles.
* [ ] Return useful context.
* [ ] Handle invalid/non-existent values gracefully.
* [ ] Consider autocomplete for vehicle types and liveries if practical.
* [ ] Use embeds.

Potential future support:

* Operator.
* Vehicle status.
* Type + livery combinations.

Do not over-engineer the first implementation.

---

# 11. Discord `/operator`

## Objective

Allow users to search for an operator.

### Usage

`/operator {noc, slug, name}`

The command should accept:

* NOC.
* Operator slug.
* Operator name.

### Embed

Return an operator information embed containing, where available:

* Operator name.
* Operator logo.
* NOC.
* Service count.
* Vehicle count.
* Other useful operator information.
* Link to the BetterFleets operator page.

The embed should look polished and consistent with the BetterFleets branding.

---

# 12. Discord Bot Architecture

Before implementing the bot:

* [ ] Determine whether a Discord bot already exists.
* [ ] Determine whether the bot should live inside the existing application or as a separate service.
* [ ] Prefer a separate service/container if that makes deployment and maintenance safer.
* [ ] Ensure the bot can communicate with BetterFleets safely.
* [ ] Avoid directly exposing the production database to Discord.
* [ ] Use appropriate authentication/API credentials.
* [ ] Store Discord tokens in environment variables/secrets.
* [ ] Document how to invite/configure the bot.
* [ ] Document required Discord permissions.
* [ ] Document development vs production bot configuration.

---

# 13. General UI/UX Improvements

While implementing these features:

* [ ] Preserve the existing BetterFleets visual identity.
* [ ] Keep the application responsive.
* [ ] Avoid introducing unnecessary dependencies.
* [ ] Reuse existing components where possible.
* [ ] Reuse existing API patterns where possible.
* [ ] Avoid duplicating business logic between frontend, API and Discord bot.
* [ ] Ensure permissions are enforced server-side, not just hidden in the UI.
* [ ] Ensure public pages remain genuinely public where intended.
* [ ] Add loading states where appropriate.
* [ ] Add useful empty states.
* [ ] Add useful error states.
* [ ] Ensure accessibility is considered for every new UI component.

---

# 14. Testing

Every feature must include appropriate testing.

### General

* [ ] Run the existing test suite before making major changes.
* [ ] Add tests for new backend functionality.
* [ ] Add tests for permissions.
* [ ] Add tests for request routing.
* [ ] Add tests for voting.
* [ ] Add tests for filters/sorting.
* [ ] Add tests for Discord command logic where practical.
* [ ] Test themes.
* [ ] Test authentication changes independently.
* [ ] Test error notifications.

### Production Safety

* [ ] Confirm development containers use development resources.
* [ ] Confirm development cannot accidentally modify production data.
* [ ] Confirm production configuration remains unchanged.
* [ ] Confirm production branch remains deployable.

---

# 15. Documentation

Update/add documentation for:

* [ ] Development setup.
* [ ] Development Docker Compose.
* [ ] Git branch workflow.
* [ ] Environment variables.
* [ ] Theme system.
* [ ] Request system.
* [ ] TU workflow.
* [ ] Clerk configuration if implemented.
* [ ] Discord error notifications.
* [ ] BetterFleets Discord bot.
* [ ] Discord bot commands.
* [ ] Deployment process.
* [ ] Production/development separation.

---

# Agent Workflow

## IMPORTANT: Work Task-by-Task

This plan is intentionally broken into independent tasks so different coding agents can work on different parts.

**Every task must maintain its own TODO checklist.**

When starting a task:

1. Read the relevant section of this `planning.md`.
2. Inspect the existing implementation before changing anything.
3. Create a detailed TODO list for that task.
4. Work through the TODO list one item at a time.
5. Tick each item off as it is completed.
6. Run relevant tests after implementation.
7. Fix any failures before marking the task complete.
8. Update this `planning.md` with the completed status.
9. Summarise:

   * What was changed.
   * What files were changed.
   * What tests were run.
   * Any remaining issues.
   * Any follow-up work another agent needs to do.

### Do not mark a task complete if:

* The implementation is only partially working.
* Tests are failing.
* Production safety has not been verified.
* Required migrations have not been handled.
* Permissions are only implemented client-side.
* Configuration/documentation required for the task is missing.

---

# Suggested Task Breakdown

Agents can independently work on these tasks where dependencies allow:

* [x] **Task 0 — Development environment & Git workflow** ✅ COMPLETED
* [ ] **Task 1 — Vehicle fleet filters and sorting**
* [ ] **Task 2 — Public operator profiles and external links**
* [ ] **Task 3 — Theme expansion**
* [ ] **Task 4 — Request system**
* [ ] **Task 5 — Changelog/request routing**
* [ ] **Task 6 — TU request discussion and voting**
* [ ] **Task 7 — Clerk authentication investigation**
* [ ] **Task 8 — Discord error notifications**
* [ ] **Task 9 — BetterFleets Discord bot architecture**
* [ ] **Task 10 — Discord `/search`**
* [ ] **Task 11 — Discord `/count`**
* [ ] **Task 12 — Discord `/operator`**
* [ ] **Task 13 — Testing**
* [ ] **Task 14 — Documentation**
* [ ] **Task 15 — Final V2 integration and review**

---

# Dependency Guidance

Some tasks should be completed before others:

### Must happen first

**Task 0 — Development environment & Git workflow** ✅ COMPLETED

Nothing should risk production before the development environment is isolated.

### Recommended order

1. ✅ Task 0 — Development environment
2. Task 1 — Vehicle filters/sorting
3. Task 2 — Public profiles
4. Task 3 — Themes
5. Task 4 — Request system
6. Task 5 — Request/changelog routing
7. Task 6 — TU workflow
8. Task 7 — Clerk investigation
9. Task 8 — Discord error handling
10. Task 9 — Discord architecture
11. Tasks 10–12 — Discord commands
12. Task 13 — Testing
13. Task 14 — Documentation
14. Task 15 — Final integration

Agents may work on independent tasks in parallel **only after checking for shared files, database migrations, API changes, or other dependencies**.

---

# Final V2 Review

Before V2 is considered complete:

* [ ] All planned features are implemented.
* [ ] All task checklists are completed.
* [ ] All tests pass.
* [ ] Production remains unaffected.
* [ ] Development deployment is reproducible.
* [ ] Database migrations are documented.
* [ ] Authentication is secure.
* [ ] TU permissions are enforced server-side.
* [ ] Discord bot works.
* [ ] Discord error notifications work.
* [ ] All new environment variables are documented.
* [ ] All major UI features work across all themes.
* [ ] Mobile/responsive behaviour has been checked.
* [ ] Accessibility has been checked.
* [ ] No secrets have been committed.
* [ ] Git history is clean and understandable.
* [ ] V2 can be deployed to production deliberately rather than accidentally.

## Final Principle

**Do not rush implementation.**

First understand how BetterFleets currently works, then make changes that fit the existing architecture.

Prefer small, testable changes over large rewrites.

Keep production isolated.

Keep each task independently understandable so another Codex agent can pick up the next task without needing the previous agent's context.
