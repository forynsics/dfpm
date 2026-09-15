# Choosing where dfpm stores its data

On Windows, dfpm uses `%LOCALAPPDATA%\dfpm` by default. On Linux it uses `$XDG_DATA_HOME/dfpm`, which is `~/.local/share/dfpm` when that variable is unset. To put the complete data root on another drive or in another directory, save a persistent root:

```powershell
dfpm config set root D:\dfpm
dfpm paths
```

Every later CLI and local-interface command uses that root. Tools, verified downloads, package records, command shortcuts, the synced catalog and transaction staging remain together beneath it.

The fixed configuration file shown by `dfpm paths` stays under the platform's configuration location: `%LOCALAPPDATA%\dfpm\config.json` on Windows, and `$XDG_CONFIG_HOME/dfpm/config.json` (normally `~/.config/dfpm/config.json`) on Linux. It is deliberately separate from a relocated data root: dfpm must be able to find this small bootstrap setting before it knows where the data root is.

## Precedence

The one-command `--root` option overrides the saved setting without changing it:

```powershell
dfpm --root E:\temporary-dfpm paths
```

Without `--root`, dfpm uses the saved root. Without either, it uses `%LOCALAPPDATA%\dfpm` on Windows or `~/.local/share/dfpm` on Linux.

Use these commands to inspect or clear the setting:

```powershell
dfpm config show
dfpm config unset root
```

Changing or clearing the setting does not move, merge or delete existing files. Future commands simply begin using the selected root. Check `dfpm paths` before installing anything, and move an existing installation separately if that is what you intend.

## WSL

dfpm inside WSL is an ordinary Linux installation. It keeps its own root in the Linux home directory, installs Linux builds, and neither sees nor touches what a Windows dfpm on the same machine has installed. That holds even though WSL passes Windows variables such as `LOCALAPPDATA` through: the root follows the operating system dfpm is running on, never an inherited variable.

Keep a WSL root on the Linux filesystem rather than under `/mnt/c`. Windows drives mounted there do not record Linux permissions by default, so every file appears executable and dfpm cannot tell a program from a data file; the drive is also case-insensitive, and much slower for tools that ship thousands of small rule files.
