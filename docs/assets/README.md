# README preview images

These PNGs are exports of Agent Rotate 0.2.0's actual `dashboard.render()` output, using isolated sample account metadata. They illustrate the terminal interface; they are not desktop captures or evidence of live provider usage.

- `dashboard.png`: four ready accounts, quota windows, and two routed sessions.
- `routing-health.png`: a quota cooldown, a login requiring repair, a stale reading, and session routing decisions.

All names, directories, usage values, session IDs, and health states are synthetic. The generator uses a temporary metadata store and a fixed clock, reads no native credentials, makes no provider requests, and deletes its temporary files. Terminal window decoration comes from Rich's SVG exporter. No account settings or runtime behavior are changed.

To regenerate, install `librsvg` (`rsvg-convert`) and the Menlo font, then run from the repository root:

```sh
uv run python scripts/render_readme_previews.py
```

The checked-in images were rendered on macOS with Menlo. Font availability can affect layout on other systems. This rendering dependency is only for updating documentation images; Agent Rotate does not require it at runtime.
