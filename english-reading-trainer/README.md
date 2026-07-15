# English Reading Trainer

## Run the local web app

From the project root, start the development server with a stable local access
token:

```sh
.venv/bin/python -m app.web.launcher --reload --access-token dev-local-token
```

Open the URL printed by the command. Keep the browser tab open while you work.

`--reload` watches the source files and restarts the server automatically after
code changes, so you normally do not need to stop it with `Ctrl+C`.

### Stop and start it manually without losing your place

Press `Ctrl+C`, then run exactly the same command again (especially keep the
same `--access-token` and port). The browser tab can stay open; reload it once
the server is running again.

The reader saves its current book, chapter, top visible sentence, and open
analysis panel in this browser's local storage. It restores that state after a
reload or server restart. Other page scroll positions are kept for the current
browser session.

Do not use a private/incognito window or clear site data if you need this
restore behavior. If you start the launcher without `--access-token`, it makes
a new token for each new shell process; the existing tab will then be denied
access and you must open the newly printed URL instead.
