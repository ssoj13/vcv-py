# vcvars

Fast Visual Studio environment setup. **~13x faster** than `vcvars64.bat`.

| | Time |
|---|---:|
| `vcvars.py` | ~150ms |
| `vcvars64.bat` | ~2000ms |

## Why?

Microsoft's `vcvars64.bat` is slow because it:
- Spawns PowerShell for telemetry
- Runs 15+ batch files sequentially
- Queries registry 4+ times
- Searches directories with `dir` commands

This script does the same job with:
- Single `vswhere.exe` call (~20ms)
- Single registry lookup
- Direct file reads
- Zero telemetry

## Installation

```powershell
# Clone or just download vcvars.py
git clone https://github.com/user/vcvars
```

No dependencies. Just Python 3.10+ and Windows.

## Usage

### PowerShell

```powershell
# Apply environment
python vcvars.py | iex

# Or add to $PROFILE
function vcvars { python C:\path\to\vcvars.py @args | iex }
```

### CMD

```cmd
python vcvars.py -f cmd > env.bat && call env.bat
```

### Bash / MSYS2

```bash
eval $(python vcvars.py -f sh)
```

### JSON (for tools)

```powershell
python vcvars.py -f json
```

## Options

```
-a, --arch    Target architecture: x64 (default), x86, arm64
-H, --host    Host architecture: x64 (default), x86, arm64
-f, --format  Output format: ps (default), cmd, sh, bash, json
-q, --quiet   Suppress info messages
```

## Examples

```powershell
# x64 native (default)
python vcvars.py | iex

# x86 target
python vcvars.py -a x86 | iex

# Cross-compile for ARM64
python vcvars.py -a arm64 | iex

# JSON for parsing
python vcvars.py -f json | ConvertFrom-Json
```

## Output

Sets these environment variables:

| Variable | Description |
|----------|-------------|
| `PATH` | Compiler binaries, SDK tools |
| `INCLUDE` | Headers (VC++, SDK, UCRT) |
| `LIB` | Libraries for linking |
| `LIBPATH` | Assembly references |
| `VCToolsInstallDir` | VC++ toolset path |
| `WindowsSdkDir` | Windows SDK path |
| `UCRTVersion` | Universal CRT version |

## License

MIT
