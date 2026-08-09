# Elves product context

## Purpose

Elves helps a developer hand a well-planned run to a separate coding worker, watch the work without
keeping the planning agent busy, and return to the main agent for review and landing.

## Users

The primary user already works in Claude Code, Codex, Grok Build, or Oh My Pi (`omp`). They may also
have Devin CLI or another supported worker, but Elves must remain useful with one host subscription.
Supported main drivers are Claude Code, Codex, Grok Build, and Oh My Pi (omp). All four use the same
automatic required-mode prewalk qualification and explicit experimental mode. Grok Build remains an
optional worker under Claude/Codex when permitted. Oh My Pi as `omp-cli` (and the `/omp` shortcut)
remains an optional worker under other hosts; that is separate from the `omp` main-driver host.
The user owns merge authorization; the host enforces it.

The public guide should lead with a copy-ready agent install/orient prompt, then shell install and
first-run kickoffs.

## Platform

`web`

## Public guide

The guide is a working manual. A reader should be able to install Elves, start a run, understand the
worker choice, watch progress, and finish safely without first learning the internal architecture.

The page should feel like a well-edited field manual beside a terminal. It should be calm, exact,
and easy to scan in daylight or at night. It is not a landing page and should not use sales copy,
decorative metrics, repeated cards, or ornamental motion.

## Voice

- Direct and specific
- Helpful without chatter
- Honest about capability and fallbacks
- Consistent across Claude Code and Codex

Use ordinary words. Prefer short paragraphs and real commands. Do not use em dashes or emojis.

## Accessibility

Target WCAG AA. Use semantic HTML, visible keyboard focus, sufficient contrast, useful link text,
responsive layouts, and reduced-motion behavior.
