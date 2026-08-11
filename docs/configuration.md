# Choosing where dfpm stores its data

On Windows, dfpm uses `%LOCALAPPDATA%\dfpm` by default. To put the complete data root on another drive or in another directory, save a persistent root:

```powershell
dfpm config set root D:\dfpm
dfpm paths
```

Every later CLI and local-interface command uses that root. Tools, verified downloads, package records, command shortcuts, the synced catalog and transaction staging remain together beneath it.

The fixed configuration file shown by `dfpm paths` stays under the platform's configuration location. It is deliberately separate from a relocated data root: dfpm must be able to find this small bootstrap setting before it knows where the data root is.

## Precedence

The one-command `--root` option overrides the saved setting without changing it:

```powershell
dfpm --root E:\temporary-dfpm paths
```

Without `--root`, dfpm uses the saved root. Without either, it uses `%LOCALAPPDATA%\dfpm` on Windows or the platform data directory elsewhere.

Use these commands to inspect or clear the setting:

```powershell
dfpm config show
dfpm config unset root
```

Changing or clearing the setting does not move, merge or delete existing files. Future commands simply begin using the selected root. Check `dfpm paths` before installing anything, and move an existing installation separately if that is what you intend.
