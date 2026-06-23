# jp-utils add-on

Configure this from **Tools -> jp-utils Settings…** (friendlier than editing the
JSON below). All settings here are also editable as raw JSON.

- **server_url** - base URL of your jp-utils backend, e.g. `http://localhost:9618`
  (or wherever the backend runs on your network).
- **token** - the bearer token the backend requires on `/v1` routes
  (`JP_UTILS_API_TOKEN` on the server). Use **Test connection** in the settings
  dialog to verify the URL and token together.
- **note_types** - per note-type **alias maps**: each binds a logical alias (e.g.
  `sentence`, `word-reading`) to the actual field on that note type. One flat
  `{alias: field}` map per note type; whether an alias is read or written is a
  property of each operation, not the binding. Seeded with defaults for the
  **Lapis** note type; remap any field or add other note types from the settings
  dialog.
- **pipelines** - ordered operations bound to a **(deck, note type)**. Each
  pipeline has a `deck` and `note_type` (both required; the pair must be unique),
  an `enabled` flag, `steps` (each an operation `op` key + a `params` map of that
  operation's options, e.g. `only_if_empty` for field-writing operations), and
  `auto_triggers` - the Anki-lifecycle events this pipeline runs on automatically:
  currently just `start` (on profile open); empty means manual-only. Each pipeline
  chooses its own triggers. Pipelines also run manually
  from the settings dialog's **Run now** button or the Browser **Notes ->
  jp-utils: Run pipeline** action. Empty by default - create your pipelines (e.g.
  one per deck) in the settings dialog.
