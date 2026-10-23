#!/usr/bin/env python3
"""build manifest.json for the modupdater mod from a curseforge instance (or any mods folder).

typical run (from the pack-repo folder):
  python tools/make_manifest.py --instance "C:/Users/Derpy/curseforge/minecraft/Instances/server pack" --repo . \
      --file config/punchy/punchy_config.json

what it does:
  * every *.jar in the instance's mods folder (plus any --extra-jar) is listed with id/version/name read from
    its fabric.mod.json, sha256 and size
  * jars curseforge knows about (minecraftinstance.json installedAddons with a downloadUrl) are linked straight
    to the curseforge cdn, nothing gets copied, so the repo stays small and we're not re-hosting other people's mods
  * everything else (your own mods, pat's mods, anything untracked) is copied into <repo>/mods and linked
    relative to the manifest (raw.githubusercontent.com serves them)
  * --file config/whatever.json copies that file from the instance into <repo>/files/ and lists it; add
    :overwrite to force it onto clients even if they already have one (default: only added when missing)
  * mod ids that were in the previous manifest but aren't any more go in "remove", so clients delete them

options:
  --mods-dir DIR      use this folder instead of <instance>/mods
  --files-from DIR    where --file paths are read from (default: the instance dir)
  --version TEXT      pack version label shown to players (default: today's date)
  --pack TEXT         pack name shown to players
  --base-url URL      prefix for hosted jar/file urls instead of relative paths (e.g. a github release)
  --no-cdn            host every jar in the repo, ignore curseforge urls
  --verify            HEAD each curseforge url and check the size matches the local jar
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_fmj(jar):
    """(id, version, name) from fabric.mod.json, or None."""
    try:
        with zipfile.ZipFile(jar) as z:
            if "fabric.mod.json" not in z.namelist():
                return None
            raw = z.read("fabric.mod.json").decode("utf-8", "replace")
    except (zipfile.BadZipFile, OSError) as e:
        print(f"  !! can't open {os.path.basename(jar)}: {e}")
        return None
    try:
        o = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r'"id"\s*:\s*"([^"]+)"', raw)
        v = re.search(r'"version"\s*:\s*"([^"]+)"', raw)
        n = re.search(r'"name"\s*:\s*"([^"]+)"', raw)
        return (m.group(1), v.group(1) if v else "", n.group(1) if n else m.group(1)) if m else None
    if "id" not in o:
        return None
    return o["id"], str(o.get("version", "")), str(o.get("name") or o["id"])


def cf_urls(instance):
    """fileName -> (downloadUrl, fileLength) from minecraftinstance.json."""
    out = {}
    p = os.path.join(instance, "minecraftinstance.json")
    if not os.path.isfile(p):
        return out
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    for a in d.get("installedAddons", []):
        fi = a.get("installedFile") or {}
        if fi.get("fileName") and fi.get("downloadUrl"):
            out[fi["fileName"]] = (fi["downloadUrl"], int(fi.get("fileLength") or 0))
    return out


def remote_size(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "modupdater-manifest/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers.get("Content-Length") or -1)
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instance", help="curseforge instance folder")
    ap.add_argument("--mods-dir")
    ap.add_argument("--files-from")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--version", default=dt.date.today().isoformat())
    ap.add_argument("--pack", default=None)
    ap.add_argument("--base-url", default="")
    ap.add_argument("--extra-jar", action="append", default=[])
    ap.add_argument("--file", action="append", default=[], help="relative path[:overwrite]")
    ap.add_argument("--no-cdn", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    if not a.instance and not a.mods_dir:
        ap.error("need --instance or --mods-dir")
    mods_dir = a.mods_dir or os.path.join(a.instance, "mods")
    files_from = a.files_from or a.instance or "."
    repo = os.path.abspath(a.repo)
    repo_mods = os.path.join(repo, "mods")
    repo_files = os.path.join(repo, "files")
    manifest_path = os.path.join(repo, "manifest.json")
    os.makedirs(repo_mods, exist_ok=True)

    prev = {}
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            prev = json.load(f)
    prev_mods = {m["id"]: m for m in prev.get("mods", [])}

    cdn = {} if a.no_cdn else cf_urls(a.instance or "")
    base = a.base_url.rstrip("/") + "/" if a.base_url else ""

    jars = sorted(
        [os.path.join(mods_dir, f) for f in os.listdir(mods_dir) if f.lower().endswith(".jar")],
        key=str.lower,
    ) + [os.path.abspath(j) for j in a.extra_jar]

    mods, hosted, seen_ids = [], set(), {}
    for jar in jars:
        name = os.path.basename(jar)
        info = read_fmj(jar)
        if not info:
            print(f"  !! skipping {name}: no fabric.mod.json (clients couldn't match it by id)")
            continue
        mid, ver, title = info
        if mid in seen_ids:
            print(f"  !! skipping {name}: id '{mid}' already provided by {seen_ids[mid]}")
            continue
        seen_ids[mid] = name
        size = os.path.getsize(jar)
        entry = {"id": mid, "name": title, "version": ver, "file": name, "sha256": sha256(jar), "size": size}
        if name in cdn:
            url, cf_len = cdn[name]
            if cf_len and cf_len != size:
                print(f"  !! {name}: curseforge says {cf_len} bytes, local is {size}, hosting it ourselves instead")
            else:
                if a.verify:
                    rs = remote_size(url)
                    if rs != size:
                        print(f"  !! {name}: cdn size {rs} != local {size}, hosting it ourselves instead")
                        url = None
                if url:
                    entry["url"] = url
        if "url" not in entry:
            dest = os.path.join(repo_mods, name)
            if not os.path.isfile(dest) or sha256(dest) != entry["sha256"]:
                shutil.copy2(jar, dest)
            hosted.add(name)
            entry["url"] = base + "mods/" + urllib.parse.quote(name)
        mods.append(entry)

    # drop hosted jars that aren't in the pack any more
    for f in os.listdir(repo_mods):
        if f.lower().endswith(".jar") and f not in hosted:
            os.remove(os.path.join(repo_mods, f))
            print(f"  removed stale hosted jar {f}")

    files = []
    for spec in a.file:
        rel, _, flag = spec.partition(":")
        rel = rel.replace("\\", "/").strip("/")
        src = os.path.join(files_from, rel)
        if not os.path.isfile(src):
            print(f"  !! file not found: {src}")
            sys.exit(1)
        dest = os.path.join(repo_files, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
        files.append({
            "path": rel,
            "url": base + "files/" + "/".join(urllib.parse.quote(p) for p in rel.split("/")),
            "sha256": sha256(src),
            "size": os.path.getsize(src),
            "overwrite": flag == "overwrite",
        })

    current_ids = set(seen_ids)
    remove = sorted((set(prev_mods) | set(prev.get("remove", []))) - current_ids)

    mods.sort(key=lambda m: m["name"].lower())
    manifest = {
        "pack": a.pack or prev.get("pack") or "server pack",
        "version": a.version,
        "minecraft": "1.21.1",
        "mods": mods,
        "remove": remove,
        "files": files,
    }
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    added = [m for m in mods if m["id"] not in prev_mods]
    updated = [m for m in mods if m["id"] in prev_mods and prev_mods[m["id"]]["sha256"] != m["sha256"]]
    print(f"manifest {manifest['version']}: {len(mods)} mods ({len(hosted)} hosted here, {len(mods) - len(hosted)} on curseforge cdn), "
          f"{len(files)} files, {len(remove)} in remove list")
    for m in added:
        print(f"  + {m['name']} {m['version']}")
    for m in updated:
        print(f"  ^ {m['name']} {prev_mods[m['id']].get('version')} -> {m['version']}")
    for r in remove:
        if r not in prev.get("remove", []):
            print(f"  - {r}")
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()
