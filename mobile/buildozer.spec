[app]
title = QuickRent
package.name = quickrent
package.domain = org.quickrent

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
android.permissions = INTERNET
android.archs = arm64-v8a,armeabi-v7a

# AndroidX is required by modern dependencies/toolchains.
android.enable_androidx = True

# Automatically accept Android SDK licenses in CI/non-interactive builds.
android.accept_sdk_license = True

