# The local management interface

```powershell
dfpm gui
dfpm gui --port 8765          # default; use --port 0 to take any free port
dfpm gui --no-browser         # start the server without opening a browser
```

`dfpm gui` serves a management interface backed by the same core the command line uses, then opens it in a browser. It lists installed packages, browses the catalog, shows health results, and performs installs, updates and removal. Every change shows the same plan the command line prints and waits for confirmation.

## It is built for one local operator

Not for shared or remote use, and it enforces that rather than assuming it:

- It binds loopback only, and refuses to bind any other address.
- Each run mints a session token, delivered in the served page and required on every API request.
- Requests carrying an unexpected `Host` or a foreign `Origin` are rejected, which blocks DNS rebinding and cross-site requests.
- Changes must arrive as `application/json`, so a cross-origin form cannot reach them.
- One change runs at a time.

## Where things live

```text
catalog\                       Entries this machine can install from
tools\<package-id>\<version>\  The installed version
cache\sha256\                  Verified downloaded artifacts
bin\                           Command shortcuts
state\packages\                Records of what was installed
```

On Windows these sit under `%LOCALAPPDATA%\dfpm` by default. `dfpm paths` prints the real locations, `dfpm config set root <dir>` saves a different root for future commands, and `--root <dir>` overrides it for one command. Changing the setting does not move an existing installation.

## The public site

There is also a public site, which explains dfpm and browses the catalog but installs nothing. It shares the local interface's visual system and reads the same catalog feed.

---

See also: [installing](installing.md) · [the catalog](catalog.md)
