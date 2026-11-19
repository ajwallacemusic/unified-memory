---
name: coding-preferences
description: How Wren likes code written and reviewed, style, tests, commits, pull requests
---
- [stated] Prefers table-driven tests in Go; dislikes mocking frameworks and would rather write small fakes
- [stated] Commit messages follow Conventional Commits, subject line under 60 characters
- [stated] Wants pull requests under 350 changed lines and splits anything bigger
- [stated] Squash merges at work; rebase merges on pgdrift
- [stated] Writes SQL by hand and generates the Go code with sqlc; does not want an ORM
- [stated] Wants a failing test written before any bug fix
- [stated] In reviews, minor remarks are prefixed "nit:" and never block a merge
- [stated] Branch names are initials/ticket-number-short-description, for example wh/1423-quote-cache
- [stated] Every pull request that touches production gets a rollback note in its description
