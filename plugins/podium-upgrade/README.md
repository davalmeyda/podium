# podium-upgrade

Claude Code plugin containing the explicitly invoked `agents-upgrade` skill. The skill researches and proposes a complete model roster update based on live evidence and the active podium configuration. It changes only `podium.toml`, then uses `podium install` to render managed files.

The scripts provide a read-only roster/preflight inventory, provider catalogs and agent checks, and CLI updates using the detected installation method. Persistent run history belongs under the podium state directory, never in this plugin.
