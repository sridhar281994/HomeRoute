[app]
title = QuickRent
package.name = quickrent
package.domain = org.quickrent

# Use the same PNG for app icon and presplash.
icon.filename = assets/QuickRent.png
presplash.filename = assets/QuickRent.png

# Your main.py lives inside the mobile/ folder.
source.dir = .
source.main = main.py
source.include_exts = py,kv,png,jpg,jpeg,svg,json,txt,ttf,ttc

# Core dependencies
# Include certifi so the CA bundle is packaged (prevents SSL errors on device),
# and pyjnius because the app uses Android billing via PyJNIus.
requirements = python3,kivy,requests,certifi,pyjnius

# App versioning
version = 0.1.0

# UI
orientation = portrait
fullscreen = 0

[buildozer]
log_level = 2

[android]
# Target API level for the Gradle project (compileSdk/targetSdk).
android.api = 34
android.minapi = 21
android.ndk = 25b
# Core + feature permissions:
# - INTERNET/ACCESS_NETWORK_STATE: network (OTP/login/API)
# - CAMERA: optional capture
# - RECORD_AUDIO/MODIFY_AUDIO_SETTINGS: audio capture + routing
android.permissions = INTERNET,CAMERA,RECORD_AUDIO,MODIFY_AUDIO_SETTINGS,ACCESS_NETWORK_STATE
android.archs = arm64-v8a,armeabi-v7a

# AndroidX is required by modern dependencies/toolchains.
android.enable_androidx = True

# Google Sign-In (used by "Login via Gmail").
android.gradle_dependencies = com.google.android.gms:play-services-auth:21.0.0

# Automatically accept Android SDK licenses in CI/non-interactive builds.
android.accept_sdk_license = True

