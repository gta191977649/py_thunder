from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

APP_NAME = "PyThunder"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAIN_SCRIPT = PROJECT_ROOT / "main.py"
RESOURCES_DIR = PROJECT_ROOT / "resources"


def get_platform_key() -> str:
    if sys.platform.startswith("win"):
        return "win"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def get_platform_label() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def get_aria2_binary_path(platform_key: str) -> Path:
    binary_name = "aria2c.exe" if platform_key == "win" else "aria2c"
    return RESOURCES_DIR / "aria2" / platform_key / binary_name


def ensure_unix_executable(path: Path) -> None:
    if sys.platform.startswith("win") or not path.exists():
        return
    current_mode = path.stat().st_mode
    path.chmod(
        current_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )


def validate_inputs(allow_missing_aria2: bool) -> None:
    required_paths = [
        MAIN_SCRIPT,
        RESOURCES_DIR,
        RESOURCES_DIR / "font" / "default.ttf",
        RESOURCES_DIR / "themes" / "classic_blue.json",
    ]

    missing_paths = [path for path in required_paths if not path.exists()]
    if missing_paths:
        missing_list = "\n".join(f"  - {path}" for path in missing_paths)
        raise SystemExit(f"Required files are missing:\n{missing_list}")

    aria2_binary = get_aria2_binary_path(get_platform_key())
    if aria2_binary.exists():
        ensure_unix_executable(aria2_binary)
        return

    message = (
        "Bundled aria2 binary is missing for the current platform.\n"
        f"Expected: {aria2_binary}\n"
        "The app can still be packaged, but downloads will not work until the "
        "binary is added."
    )
    if allow_missing_aria2:
        print(f"WARNING: {message}")
        return
    raise SystemExit(message)


def ensure_pyinstaller_available() -> None:
    try:
        __import__("PyInstaller")
    except ImportError as exc:
        raise SystemExit(
            "PyInstaller is not installed.\n"
            "Run: python -m pip install -r requirements-build.txt"
        ) from exc


def remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def build_pyinstaller_args(mode: str, dist_dir: Path, work_dir: Path, spec_dir: Path) -> list[str]:
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--paths",
        str(PROJECT_ROOT),
        "--add-data",
        f"{RESOURCES_DIR}{os.pathsep}resources",
        str(MAIN_SCRIPT),
    ]
    if mode == "onefile":
        args.append("--onefile")
    else:
        args.append("--onedir")
    return args


def find_artifact(dist_dir: Path) -> Path:
    preferred_names = [
        APP_NAME,
        f"{APP_NAME}.exe",
        f"{APP_NAME}.app",
    ]
    for name in preferred_names:
        candidate = dist_dir / name
        if candidate.exists():
            return candidate

    children = [path for path in dist_dir.iterdir() if path.name != "__pycache__"]
    if len(children) == 1:
        return children[0]

    raise RuntimeError(f"Could not determine build artifact in: {dist_dir}")


def zip_artifact(artifact: Path, archive_path: Path) -> Path:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    remove_path(archive_path)

    if artifact.is_file():
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(artifact, arcname=artifact.name)
        return archive_path

    shutil.make_archive(
        str(archive_path.with_suffix("")),
        "zip",
        root_dir=artifact.parent,
        base_dir=artifact.name,
    )
    return archive_path


def build_mode(mode: str, clean: bool) -> tuple[Path, Path]:
    platform_label = get_platform_label()
    dist_dir = PROJECT_ROOT / "release" / platform_label / mode
    work_dir = PROJECT_ROOT / "build" / "pyinstaller" / platform_label / mode
    spec_dir = PROJECT_ROOT / "build" / "spec" / platform_label / mode
    archive_path = PROJECT_ROOT / "release" / platform_label / f"{APP_NAME}-{platform_label}-{mode}.zip"

    if clean:
        remove_path(dist_dir)
        remove_path(work_dir)
        remove_path(spec_dir)
        remove_path(archive_path)

    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    command = build_pyinstaller_args(mode, dist_dir, work_dir, spec_dir)
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)

    artifact = find_artifact(dist_dir)
    archive = zip_artifact(artifact, archive_path)
    return artifact, archive


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a portable PyInstaller package for the current platform."
    )
    parser.add_argument(
        "--mode",
        choices=("portable", "onefile", "both"),
        default="portable",
        help="portable=onedir green package, onefile=single executable, both=build both variants.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete prior build outputs for the selected mode before packaging.",
    )
    parser.add_argument(
        "--allow-missing-aria2",
        action="store_true",
        help="Build even when the bundled aria2 binary is missing for this platform.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_pyinstaller_available()
    validate_inputs(args.allow_missing_aria2)

    modes = ["portable", "onefile"] if args.mode == "both" else [args.mode]

    print(f"Packaging {APP_NAME} for {get_platform_label()}...")
    for mode in modes:
        artifact, archive = build_mode(mode, clean=args.clean)
        print(f"[{mode}] artifact: {artifact}")
        print(f"[{mode}] archive:  {archive}")

    print("Packaging finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
