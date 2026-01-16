[app]
#
# Keep `source.dir = .` so the packaged app preserves Python package layout
# (e.g. `frontend_app.*` stays importable).
#
title = QuickRent
package.name = quickrent
package.domain = org.quickrent

# Your main.py lives inside the mobile/ folder.
source.dir = .
source.main = main.py
source.include_exts = py,kv,png,jpg,jpeg,svg,json,txt,ttf,ttc,atlas

# Core dependencies
#
# Include certifi so CA bundle is always packaged (prevents SSL issues on device).
#
requirements = python3,kivy,requests,certifi,pyjnius

# App versioning
version = 0.1.0

# UI
orientation = portrait
fullscreen = 0

[buildozer]
log_level = 2

[android]
android.enable_androidx = True

# Target Android API (compileSdk/targetSdk).
android.api = 34
android.minapi = 21
android.permissions = INTERNET

# Strip debug symbols from native libs to reduce artifact size.
android.strip = True

# Architectures to build for.
android.archs = arm64-v8a,armeabi-v7a

[app:source.exclude_patterns]
# Never ship caches / build output.
__pycache__/*
*/__pycache__/*
*/*/__pycache__/*
*/*/*/__pycache__/*
*.pyc
*.pyo
*.pyd
*.zip

.git/*
.github/*
.buildozer/*
bin/*
.gradle/*

