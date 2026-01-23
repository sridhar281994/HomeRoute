[app]
title = Flatnow.in
package.name = flatnow
package.domain = in.flatnow

# Use the same PNG for app icon and presplash.
icon.filename = assets/flatnow_icon.png
# Disable presplash to avoid Android auto-scaling/stretching to full screen.
# (We use the in-app `SplashScreen` instead.)
# presplash.filename = assets/flatnow_all.png

# Your main.py lives inside the mobile/ folder.
source.dir = .
source.main = main.py
source.include_exts = py,kv,png,jpg,jpeg,svg,json,txt,ttf,ttc

# (str) Application versioning
version = 0.1

# Core dependencies
# Include certifi so the CA bundle is packaged (prevents SSL errors on device).
requirements = python3,kivy,requests,certifi,pyjnius,websocket-client,plyer

# Local python-for-android recipe overrides.
p4a.local_recipes = recipes

# UI
orientation = portrait
fullscreen = 1

# Android specific
android.enable_androidx = True
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_COARSE_LOCATION,ACCESS_FINE_LOCATION,READ_MEDIA_IMAGES,READ_MEDIA_VIDEO,READ_EXTERNAL_STORAGE
android.gradle_dependencies = \
    com.google.android.gms:play-services-auth:21.0.0, \
    com.google.android.gms:play-services-base:18.5.0
android.gradle_options = -Dorg.gradle.jvmargs=-Xmx4096m
android.release_artifact = aab
android.api = 34
android.minapi = 21
android.ndk = 25b
android.copy_libs = 1
android.strip = True
android.archs = arm64-v8a,armeabi-v7a
android.allow_backup = True
android.accept_sdk_license = True
android.keystore = flatnow-debug.keystore
android.keyalias = flatnowdebug
android.keystore_password = android
android.keyalias_password = android

[buildozer]
log_level = 2
warn_on_root = 1
# build_dir = ./.buildozer
# bin_dir = ./bin

# -----------------------------------------------------------------------------
# List as sections
#
# You can define all the "list" as [section:name].
# Each line will be considered as a option to the list.
# Let's take [app] / source.exclude_patterns.
# Instead of doing:
#
#     [app]
#     source.exclude_patterns = license,data/audio/*.wav,data/images/original/*
#
# This can be translated into:
#
#     [app:source.exclude_patterns]
#     license
#     data/audio/*.wav
#     data/images/original/*
#
# -----------------------------------------------------------------------------
# Profiles
#
# You can extend section / key with a profile.
# For example, you want to deploy a demo version of your application without
# HD content. You could first change the title to add "(demo)" in the name
# and extend the excluded directories to remove the HD content.
#
#     [app@demo]
#     title = My Application (demo)
#
#     [app:source.exclude_patterns@demo]
#     images/hd/*
#
# Then, invoke buildozer with the "demo" profile:
#
#     buildozer --profile demo android debug

[app:source.exclude_patterns]
# Keep the packaged sources as small as possible.
__pycache__/*
*/__pycache__/*
*/*/__pycache__/*
*/*/*/__pycache__/*
*.pyc
*.pyo
*.pyd
*.zip

# Never ship repo metadata / build output.
.git/*
.github/*
.buildozer/*
bin/*

# Local/dev artifacts that should not be in the app bundle.
tmp_*/*
*.db
*.sqlite
*.sqlite3

# Backend/server code is not needed on-device.
routers/*
scripts/*
database.py
models.py
utils/*
app.db
render-db-migrate.yml
requirements.txt
PRODUCTION.md
core
