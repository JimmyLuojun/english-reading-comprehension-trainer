# Minimal Recursive AI Analysis

Date: 2026-06-18

## Status

Accepted

## Context

The useful learning loop for reading comprehension is recursive: understand the whole sentence, inspect the structure or lexical item that blocks understanding, return to the whole sentence, and keep a reusable check point for future reading.

The project already validates AI output through closed JSON schemas and stores results in prompt-versioned cache rows. Adding fields therefore has real cost: schema updates, validator changes, saver compatibility, cache staleness, prompt version bumps, and tests. The project also already has SM-2 Review, sentence/word cards, Takeaway, and Similar past mistake reminders.

## Decision

Implement the recursive learning loop with the smallest useful schema increment:

- Sentence analysis adds `blocking_point` and `takeaway_suggestion`.
- Word / phrase / collocation analysis adds `role_in_sentence`.
- Reader panel is reordered around the existing recursive path and gets an `Accept suggestion` action that fills the existing Takeaway input.
- No new review primitive, table, nested parse tree, or second highlighter is introduced.

## Consequences

- New analysis uses new prompt versions and older cached analyses may appear stale.
- Historical payloads remain readable because old schemas and rendering fallbacks are preserved.
- Takeaway remains the single user-editable reusable check point for sentence learning.
- Similar past mistake continues to use existing error-code links rather than a new quiz/review model.
