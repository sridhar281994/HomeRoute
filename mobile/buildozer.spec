[app]
title = QuickRent
package.name = quickrent
package.domain = org.quickrent

# Your main.py lives inside the mobile/ folder.
source.dir = .
source.main = main.py
source.include_exts = py,kv,png,jpg,jpeg,svg,json,txt,ttf,ttc

# Core dependencies
requirements = python3,kivy,requests

# App versioning
version = 0.1.0

# UI
orientation = portrait
fullscreen = 0

[buildozer]
log_level = 2

[android]
android.api = 33
android.minapi = 21
android.ndk = 25b
android.sdk = 33
android.permissions = INTERNET
android.archs = arm64-v8a,armeabi-v7a

