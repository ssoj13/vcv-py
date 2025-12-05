#!/usr/bin/env python3
"""Fast Visual Studio environment setup. ~50x faster than vcvars64.bat."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import winreg
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

Arch = Literal["x64", "x86", "arm64"]


# =============================================================================
# Core: Registry & File Helpers
# =============================================================================
def reg_val(key: int, path: str, name: str) -> Optional[str]:
	"""Read single registry value."""
	try:
		with winreg.OpenKey(key, path) as k:
			return winreg.QueryValueEx(k, name)[0]
	except OSError:
		return None


def reg_find(path: str, name: str) -> Optional[str]:
	"""Search registry value across HKLM/HKCU and Wow6432Node."""
	for key in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
		for prefix in [r"SOFTWARE\Wow6432Node", r"SOFTWARE"]:
			if val := reg_val(key, rf"{prefix}\{path}", name):
				return val
	return None


def read_txt(path: Path) -> Optional[str]:
	"""Read single-line text file."""
	return path.read_text().strip() if path.exists() else None


# =============================================================================
# VS/VC Toolset Detection
# =============================================================================
@dataclass
class VsInfo:
	install: Path
	version: str
	vc: Path
	tools_ver: str
	tools: Path


def detect_vs() -> Optional[VsInfo]:
	"""Detect VS installation via vswhere."""
	vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
	if not vswhere.exists():
		return None
	try:
		r = subprocess.run([str(vswhere), "-latest", "-format", "json", "-utf8"], capture_output=True, text=True, timeout=5)
		data = json.loads(r.stdout)
		if not data:
			return None
		vs = data[0]
	except (subprocess.TimeoutExpired, json.JSONDecodeError, IndexError):
		return None
	install = Path(vs["installationPath"])
	vc = install / "VC"
	aux = vc / "Auxiliary" / "Build"
	# Get tools version
	tools_ver = read_txt(aux / "Microsoft.VCToolsVersion.v143.default.txt") or read_txt(aux / "Microsoft.VCToolsVersion.default.txt")
	if not tools_ver:
		return None
	tools = vc / "Tools" / "MSVC" / tools_ver
	if not tools.exists():
		return None
	return VsInfo(
		install=install,
		version=vs.get("installationVersion", ""),
		vc=vc,
		tools_ver=tools_ver,
		tools=tools,
	)


# =============================================================================
# Windows SDK Detection
# =============================================================================
@dataclass
class SdkInfo:
	path: Path
	version: str


def detect_sdk() -> Optional[SdkInfo]:
	"""Find Windows 10/11 SDK."""
	sdk_path = reg_find(r"Microsoft\Microsoft SDKs\Windows\v10.0", "InstallationFolder")
	if not sdk_path:
		return None
	root = Path(sdk_path)
	inc = root / "include"
	if not inc.exists():
		return None
	# Find latest 10.x with winsdkver.h
	for d in sorted(inc.iterdir(), reverse=True):
		if d.is_dir() and d.name.startswith("10.") and (d / "um" / "winsdkver.h").exists():
			return SdkInfo(path=root, version=d.name)
	return None


def detect_ucrt() -> Optional[SdkInfo]:
	"""Find Universal CRT."""
	ucrt_path = reg_find(r"Microsoft\Windows Kits\Installed Roots", "KitsRoot10")
	if not ucrt_path:
		return None
	root = Path(ucrt_path)
	lib = root / "Lib"
	if not lib.exists():
		return None
	# Find latest 10.x with ucrt.lib
	for d in sorted(lib.iterdir(), reverse=True):
		if d.is_dir() and d.name.startswith("10.") and (d / "ucrt" / "x64" / "ucrt.lib").exists():
			return SdkInfo(path=root, version=d.name)
	return None


# =============================================================================
# Environment Builder
# =============================================================================
@dataclass
class Env:
	path: list[Path] = field(default_factory=list)
	include: list[Path] = field(default_factory=list)
	lib: list[Path] = field(default_factory=list)
	libpath: list[Path] = field(default_factory=list)
	vars: dict[str, str] = field(default_factory=dict)


def build_env(vs: VsInfo, sdk: Optional[SdkInfo], ucrt: Optional[SdkInfo], host: Arch = "x64", target: Arch = "x64") -> Env:
	"""Assemble complete environment."""
	env = Env()
	tp = vs.tools
	hd = {"x64": "Hostx64", "x86": "Hostx86", "arm64": "Hostarm64"}[host]

	def add_if_exists(lst: list, *paths: Path):
		lst.extend(p for p in paths if p.exists())

	# VC++ binaries
	add_if_exists(env.path, tp / "bin" / hd / target)
	if host != target:
		add_if_exists(env.path, tp / "bin" / hd / host)
	# VC++ headers & libs
	add_if_exists(env.include, tp / "include", tp / "ATLMFC" / "include")
	add_if_exists(env.lib, tp / "lib" / target, tp / "ATLMFC" / "lib" / target)
	add_if_exists(env.libpath, tp / "lib" / target, tp / "ATLMFC" / "lib" / target)
	# Windows SDK
	if sdk:
		sp, sv = sdk.path, sdk.version
		add_if_exists(env.path, sp / "bin" / sv / host)
		add_if_exists(env.include, sp / "include" / sv / "ucrt", sp / "include" / sv / "um", sp / "include" / sv / "shared", sp / "include" / sv / "winrt", sp / "include" / sv / "cppwinrt")
		add_if_exists(env.lib, sp / "lib" / sv / "um" / target)
		add_if_exists(env.libpath, sp / "UnionMetadata" / sv, sp / "References" / sv)
	# UCRT
	if ucrt:
		up, uv = ucrt.path, ucrt.version
		add_if_exists(env.include, up / "include" / uv / "ucrt")
		add_if_exists(env.lib, up / "lib" / uv / "ucrt" / target)
	# Standard variables
	env.vars = {
		"VSINSTALLDIR": f"{vs.install}\\",
		"VCINSTALLDIR": f"{vs.vc}\\",
		"VCToolsInstallDir": f"{tp}\\",
		"VCToolsVersion": vs.tools_ver,
		"VisualStudioVersion": "17.0",
		"Platform": target,
	}
	if sdk:
		env.vars["WindowsSdkDir"] = f"{sdk.path}\\"
		env.vars["WindowsSDKVersion"] = f"{sdk.version}\\"
	if ucrt:
		env.vars["UniversalCRTSdkDir"] = f"{ucrt.path}\\"
		env.vars["UCRTVersion"] = ucrt.version
	return env


# =============================================================================
# Output Formatters
# =============================================================================
def fmt_cmd(env: Env) -> str:
	"""Format for cmd.exe."""
	lines = []
	if env.path:
		lines.append(f'set "PATH={";".join(map(str, env.path))};%PATH%"')
	if env.include:
		lines.append(f'set "INCLUDE={";".join(map(str, env.include))};%INCLUDE%"')
	if env.lib:
		lines.append(f'set "LIB={";".join(map(str, env.lib))};%LIB%"')
	if env.libpath:
		lines.append(f'set "LIBPATH={";".join(map(str, env.libpath))};%LIBPATH%"')
	for k, v in env.vars.items():
		lines.append(f'set "{k}={v}"')
	return "\n".join(lines)


def fmt_ps(env: Env) -> str:
	"""Format for PowerShell."""
	lines = []
	if env.path:
		lines.append(f'$env:PATH = "{";".join(map(str, env.path))};$env:PATH"')
	if env.include:
		lines.append(f'$env:INCLUDE = "{";".join(map(str, env.include))};$env:INCLUDE"')
	if env.lib:
		lines.append(f'$env:LIB = "{";".join(map(str, env.lib))};$env:LIB"')
	if env.libpath:
		lines.append(f'$env:LIBPATH = "{";".join(map(str, env.libpath))};$env:LIBPATH"')
	for k, v in env.vars.items():
		lines.append(f'$env:{k} = "{v}"')
	return "\n".join(lines)


def fmt_sh(env: Env) -> str:
	"""Format for bash/MSYS2."""

	def winpath(p: str) -> str:
		if len(p) >= 2 and p[1] == ":":
			return "/" + p[0].lower() + p[2:].replace("\\", "/")
		return p.replace("\\", "/")

	lines = []
	if env.path:
		lines.append(f'export PATH="{":".join(winpath(str(p)) for p in env.path)}:$PATH"')
	if env.include:
		lines.append(f'export INCLUDE="{";".join(map(str, env.include))};$INCLUDE"')
	if env.lib:
		lines.append(f'export LIB="{";".join(map(str, env.lib))};$LIB"')
	if env.libpath:
		lines.append(f'export LIBPATH="{";".join(map(str, env.libpath))};$LIBPATH"')
	for k, v in env.vars.items():
		lines.append(f'export {k}="{v}"')
	return "\n".join(lines)


def fmt_json(env: Env) -> str:
	"""Format as JSON."""
	return json.dumps(
		{
			"PATH": [str(p) for p in env.path],
			"INCLUDE": [str(p) for p in env.include],
			"LIB": [str(p) for p in env.lib],
			"LIBPATH": [str(p) for p in env.libpath],
			**env.vars,
		},
		indent=2,
	)


FMTS = {"cmd": fmt_cmd, "ps": fmt_ps, "powershell": fmt_ps, "sh": fmt_sh, "bash": fmt_sh, "json": fmt_json}


# =============================================================================
# CLI
# =============================================================================
def main() -> int:
	p = argparse.ArgumentParser(
		description="Fast VS environment (~50x faster than vcvars64.bat)",
		epilog="Examples:\n" "  vcvars -f ps | iex		   # PowerShell\n" "  eval $(vcvars -f sh)		 # Bash/MSYS2\n" "  vcvars -f json			   # For tools",
		formatter_class=argparse.RawDescriptionHelpFormatter,
	)
	p.add_argument("-a", "--arch", choices=["x64", "x86", "arm64"], default="x64")
	p.add_argument("-H", "--host", choices=["x64", "x86", "arm64"], default="x64")
	p.add_argument("-f", "--format", choices=list(FMTS), default="ps")
	p.add_argument("-q", "--quiet", action="store_true")
	args = p.parse_args()
	vs = detect_vs()
	if not vs:
		print("Error: Visual Studio not found", file=sys.stderr)
		return 1
	sdk = detect_sdk()
	ucrt = detect_ucrt()
	if not args.quiet:
		print(f"# VS {vs.version} | VC {vs.tools_ver}", file=sys.stderr)
		if sdk:
			print(f"# SDK {sdk.version}", file=sys.stderr)
	env = build_env(vs, sdk, ucrt, host=args.host, target=args.arch)
	print(FMTS[args.format](env))
	return 0


if __name__ == "__main__":
	sys.exit(main())
