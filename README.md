# mc-server-pack

The mod list for Derpy's 1.21.1 Fabric server, read by the `modupdater` mod on everyone's client.

- `manifest.json` is what the clients fetch. One entry per mod: id, version, file name, download url, sha256, size.
- `mods/` holds the jars we host ourselves (our own mods, Pat's mods, anything no public CDN has).
  Mods that came from CurseForge point straight at the CurseForge CDN. Anything else is looked up on
  Modrinth by exact file hash and, if it's there, points at Modrinth's CDN instead of being copied here
  (`--no-modrinth` turns that off). Nothing is hosted here unless it has to be.
- `files/` holds config files the pack ships (currently `config/punchy/punchy_config.json`).
- `remove` in the manifest lists mod ids that used to be in the pack. Clients delete them.

Clients match mods by the `id` inside each jar's `fabric.mod.json` and decide "up to date" by sha256, so
version strings are only cosmetic. Jars the manifest doesn't mention are left alone, so people can keep their own
client-side mods.

## updating the pack

1. Put the new/updated jars in the CurseForge "server pack" instance's `mods` folder (and remove old ones), the
   same way as always.
2. From this folder run:

   ```
   python tools/make_manifest.py --instance "C:/Users/Derpy/curseforge/minecraft/Instances/server pack" --repo . --file config/punchy/punchy_config.json
   ```

   It rewrites `manifest.json`, copies any untracked jars into `mods/`, prunes hosted jars that are gone, and adds
   dropped mod ids to `remove`. The version label defaults to today's date (`--version whatever` to override).
3. Commit and push:

   ```
   git add -A && git commit -m "pack 2026-10-24" && git push
   ```

Next time anyone opens the game the title screen button goes yellow with the number of changes.

Options worth knowing: `--file path:overwrite` forces a config onto clients even if they already have one;
`--extra-jar some.jar` lists a jar that isn't in the instance folder; `--no-modrinth` hosts every untracked jar here; `--verify` HEAD-checks every CurseForge url;
`--base-url https://github.com/<user>/<repo>/releases/download/<tag>/` if hosted jars ever move to a release.

## notes

- The repo has to be public for `raw.githubusercontent.com` to serve it without a token.
- `.gitattributes` turns line-ending conversion off for the whole repo. Don't remove it: git for windows
  defaults to `core.autocrlf=true`, which would store a CRLF config as LF and break its sha256 on clients.
- raw.githubusercontent.com caches for up to 5 minutes, so a push can take that long to show up in game.
- The updater only reads the manifest url baked into the mod (`config/modupdater.json` on a client overrides it).

## server updater app (25 Oct 2026 onwards)

`manifest.json` is now maintained by the **Server Updater** desktop app (`server-updater/` in the project, exe for
Derpy and Pat), which edits entries by mod id over the GitHub API and commits jars into `mods/` when they aren't
on Modrinth/CurseForge. Entries carry an extra `"env"` field (`*` / `client` / `server`) that the server-side
sync reads; the client mod ignores it. `server-manifest.json` holds server-only mods and is never read by clients.
The box pulls both manifests on every start (`server-sync.jar`). Only run `tools/make_manifest.py` for a full
rebuild, after `git pull`; it drops `env`.

Since 27 Oct 2026 uploads land in **`staging.json`** (+ jars under `staging/`) first and only move into the
manifests / `mods/` when someone presses *publish + restart* in the app, so clients never get ahead of the server.
Nothing but the app reads `staging.json`; `remove` can temporarily list a mod that was published and then undone.
