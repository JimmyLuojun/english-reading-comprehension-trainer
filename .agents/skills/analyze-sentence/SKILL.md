---
name: analyze-sentence
description: Analyze and save a difficult English Reading Trainer sentence using its current project prompt. Use when the user supplies a sentence ID and wants structural analysis, diagnosis, translation guidance, or a sentence review card.
---

# Analyze a sentence

1. Work from the repository root and enter `english-reading-trainer`.
2. Render the authoritative prompt and schema:

   ```bash
   .venv/bin/python -m app.cli_entry ai prompt-sentence <sentence-id>
   ```

   When the user explicitly supplies a translation to diagnose, append
   `--translation "<translation>"`.
3. Follow the rendered prompt exactly. Do not substitute a copied schema from
   this skill. Produce the requested analysis as raw JSON without Markdown
   fences or commentary.
4. Write the raw JSON to a unique temporary UTF-8 file, then save it through
   the application boundary:

   ```bash
   .venv/bin/python -m app.cli_entry ai save-sentence <sentence-id> --input-file <response-file>
   ```

5. Leave the default model label unchanged unless the actual model identifier
   is known reliably. Report the saved cache/card result and the sentence's
   central structure and takeaway.

If validation fails, use the current rendered prompt to correct the JSON and
retry. Never write directly to SQLite or embed generated JSON in executable
shell or Python source.
