## Fixing Google Sign-In status=10 in CI (stable signing SHA-1)

Google Sign-In / Firebase OAuth returns **status=10 (DEVELOPER_ERROR)** if the app’s **package name + signing certificate SHA-1** don’t match what’s registered in Firebase / Google Cloud.

In CI, if a new debug keystore is generated on every build, the **SHA-1 changes** and sign-in will fail.

This repo’s Android CI workflow expects a **stable debug keystore** provided via a GitHub Secret.

### 1) Generate a stable debug keystore (one time)

Run locally:

```bash
keytool -genkeypair -v \
  -keystore flatnow-debug.keystore \
  -storepass android \
  -keypass android \
  -alias flatnowdebug \
  -keyalg RSA \
  -keysize 2048 \
  -validity 10000 \
  -dname "CN=Android Debug,O=Android,C=US"
```

### 2) Get its SHA-1 (register this in Firebase / Google Cloud)

```bash
keytool -list -v \
  -keystore flatnow-debug.keystore \
  -alias flatnowdebug \
  -storepass android \
  -keypass android
```

Copy the **SHA1** value.

### 3) Add the keystore to GitHub Secrets (so CI can use it)

Encode the file as base64 (single line):

```bash
base64 -w 0 flatnow-debug.keystore
```

Create a GitHub Actions secret:

- **Name**: `ANDROID_DEBUG_KEYSTORE_BASE64`
- **Value**: the base64 output from the command above

### 4) Update Firebase config

- Add the SHA-1 to your **Firebase Android app** settings (or Google Cloud OAuth client, depending on setup).
- Re-download `google-services.json` from Firebase and replace `mobile/google-services.json` if Firebase updates the OAuth section.

### Notes

- The build reads `mobile/flatnow-debug.keystore` and signs the APK with alias `flatnowdebug` (passwords are `android`/`android`).
- Keeping the keystore stable makes the SHA-1 stable, which makes Google Sign-In stable.
- The CI workflow prints the signing certificate SHA-1 from the built APK in the job logs; register **that** SHA-1 in Firebase.
