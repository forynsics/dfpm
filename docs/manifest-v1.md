# DFPM manifest format, version 1

The first implemented manifest format is intentionally narrow. It supports portable ZIP packages from local files or HTTPS sources. Broader package types and installation strategies will be added without weakening the validation rules around existing packages.

## Example

```json
{
  "schema_version": 1,
  "id": "example.tool",
  "name": "Example Tool",
  "version": "1.0.0",
  "kind": "tool",
  "description": "A short description of what the tool does.",
  "artifact": {
    "source": "https://example.org/example-tool-1.0.0.zip",
    "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "size": 1048576
  },
  "install": {
    "strategy": "portable-zip",
    "strip_components": 1,
    "entrypoints": [
      {
        "name": "example-tool",
        "path": "bin/example-tool.exe"
      }
    ]
  },
  "health_checks": [
    {
      "type": "file",
      "path": "bin/example-tool.exe"
    }
  ]
}
```

## Fields

- `schema_version` must be `1`.
- `id` is a stable lowercase package identity.
- `kind` may be `tool`, `runtime`, `ruleset`, `artifact-pack`, `parser-pack`, `integration`, or `config-pack`.
- `artifact.source` accepts an HTTPS URL, `file` URL, or path relative to the manifest.
- `artifact.sha256` is mandatory and must contain the expected SHA-256 digest.
- `artifact.size` is optional but recommended.
- `install.strategy` must currently be `portable-zip`.
- `strip_components` removes a fixed number of leading archive path components.
- Entrypoint names become stable command shims in the DFPM `bin` directory.
- File health checks verify that required files remain present. DFPM also records and checks the digest of every extracted file.

All paths inside packages must be relative and stay within the package installation directory. Archives containing parent traversal paths or symbolic links are rejected.

## Activation behavior

DFPM downloads into a content-addressed cache, verifies the artifact, extracts into a staging directory, validates expected files, and only then moves the version into its final directory and records it as active. An interrupted or invalid staged install does not become active.
