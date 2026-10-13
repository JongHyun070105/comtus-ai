#!/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
build_root="$repo_root/apps/mac-capture/.build/input-adapter-smoke"
mkdir -p "$build_root/ModuleCache"

swiftc -O -parse-as-library -module-cache-path "$build_root/ModuleCache" \
  "$repo_root"/apps/mac-capture/Sources/MacCaptureCore/*.swift \
  "$repo_root"/apps/mac-capture/Scripts/InputAdapterSmoke.swift \
  -framework AppKit -framework ApplicationServices -framework CoreGraphics \
  -framework ScreenCaptureKit -framework Vision \
  -o "$build_root/input-adapter-smoke"
"$build_root/input-adapter-smoke"
