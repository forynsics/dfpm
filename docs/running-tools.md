# Running installed tools

dfpm does not modify your PATH, so reaching an installed tool is your choice. There are three ways.

## dfpm run

The one that needs no setup:

```powershell
dfpm run yara --version
dfpm run yara rules.yar C:\evidence\collected
```

It looks up the command among the installed packages, runs that exact file, and passes your arguments through as a real argument list. dfpm never adds arguments of its own — what you type is what runs.

## dfpm which

Shows what a command resolves to before you run it:

```text
yara -> C:\Users\you\AppData\Local\dfpm\tools\yara\4.5.5\yara64.exe
  Package:  yara 4.5.5
  Runs in:  C:\Users\you\AppData\Local\dfpm\tools\yara\4.5.5
  Shortcut: C:\Users\you\AppData\Local\dfpm\bin\yara.cmd
  On PATH:  not reachable. Use 'dfpm run yara', the full path above,
            or add C:\Users\you\AppData\Local\dfpm\bin to your PATH yourself.
```

## Where a tool runs from

A command launches from the directory holding its executable rather than from wherever you happen to be standing, so a tool that keeps its rules, maps or configuration beside itself finds them from any working directory. A package can name a different directory if it expects one, and `dfpm which` shows it.

## Putting dfpm's bin directory on PATH

The second option. `dfpm paths` shows where it is. Use the Windows *Environment Variables* dialog rather than `setx`, which silently truncates PATH at 1024 characters and has wrecked a lot of environments. Newly opened terminals pick up the change.

Putting it first means dfpm's copy of a tool wins over any other copy on the machine, which is usually what you want from a toolchain manager but does mean a `yara` installed by something else is shadowed. Windows scans PATH left to right and, within a directory, tries extensions in `PATHEXT` order — where `.EXE` comes before `.CMD` — so another tool's `yara.exe` earlier on PATH beats dfpm's `yara.cmd`. `dfpm which` reports when that is happening.

The third option is to run the full path `dfpm which` prints, which is what the command shortcut does anyway.

## Exit codes

`dfpm run` returns the tool's own exit code, so it composes normally in scripts. dfpm's own refusals use the shell's conventions instead, so a script can tell them apart from anything the tool returned:

| Code | Meaning |
| --- | --- |
| `127` | No installed package provides that command |
| `126` | It resolved, but could not be launched |
| `130` | Cancelled |

`dfpm doctor` follows the same idea:

| Code | Meaning |
| --- | --- |
| `0` | Everything is ready |
| `1` | Something dfpm is responsible for is broken |
| `2` | Installed correctly, but the machine is missing a runtime it needs |

## Runtimes

dfpm detects the runtimes a package needs and reports them; it does not install them. A package installs whether or not the machine can run it yet, and says which it is:

```text
Runtime requirement:
  .NET base >=9: .NET was not found
    Install the .NET runtime from https://dotnet.microsoft.com/download

The package is installed but cannot be run yet. Run 'dfpm doctor <package-id>' for details.
```

This is checked live rather than recorded at install time, because a runtime can appear or disappear long afterwards. dfpm looks for one dfpm installed first, then on PATH, then where that runtime's installer normally puts it — a .NET application does not need `dotnet` to be a command in order to run.

## Arguments through .cmd and .bat entrypoints

When a package's entrypoint is a `.cmd` or `.bat`, Windows runs it through `cmd`, which re-reads the command line before the script ever sees it. An argument containing `&`, `|`, `<`, `>`, `^`, `(`, `)`, `"` or `%` would not arrive intact, so dfpm refuses it and points you at the file to run directly.

---

See also: [installing](installing.md) · [security model](security.md)
