#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MOD_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SDK_DIR="${ANDROID_SDK_ROOT:-/opt/android-sdk}"
BUILD_TOOLS="${BUILD_TOOLS:-$SDK_DIR/build-tools/37.0.0}"
PLATFORM_JAR="${PLATFORM_JAR:-$SDK_DIR/platforms/android-37.0/android.jar}"

OUT_DIR="$SCRIPT_DIR/build"
APK_DST="$MOD_DIR/system/system_ext/app/Gt5ChargingHistory/Gt5ChargingHistory.apk"
KEYSTORE="${GT5_KEYSTORE:-$HOME/.android/gt5_charging_release.jks}"

mkdir -p "$OUT_DIR/res_flat" "$OUT_DIR/gen" "$OUT_DIR/classes" "$OUT_DIR/dex" "$(dirname "$APK_DST")" "$(dirname "$KEYSTORE")"

if [ ! -f "$KEYSTORE" ]; then
  keytool -genkeypair -v \
    -keystore "$KEYSTORE" \
    -storepass gt5charging2026 \
    -keypass gt5charging2026 \
    -alias gt5charging \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=GT5 Charging,OU=InfinityX,O=RMX3820,L=CN,ST=CN,C=CN" >/dev/null 2>&1
fi

# 1. Compile resources with aapt2
"$BUILD_TOOLS/aapt2" compile --dir "$SCRIPT_DIR/res" -o "$OUT_DIR/res_flat/resources.zip"

# 2. Link resources + manifest -> R.java + base APK
"$BUILD_TOOLS/aapt2" link \
  -I "$PLATFORM_JAR" \
  --manifest "$SCRIPT_DIR/AndroidManifest.xml" \
  --java "$OUT_DIR/gen" \
  -o "$OUT_DIR/unaligned.apk" \
  "$OUT_DIR/res_flat/resources.zip"

# 3. Compile Java sources
find "$OUT_DIR/gen" "$SCRIPT_DIR/src" -name '*.java' > "$OUT_DIR/sources.txt"
javac --release 17 -encoding UTF-8 -classpath "$PLATFORM_JAR" -d "$OUT_DIR/classes" @"$OUT_DIR/sources.txt"

# 4. DEX with d8
"$BUILD_TOOLS/d8" --min-api 34 --lib "$PLATFORM_JAR" --output "$OUT_DIR/dex" $(find "$OUT_DIR/classes" -name '*.class')

# 5. Package classes.dex into APK
cp "$OUT_DIR/unaligned.apk" "$OUT_DIR/with_dex.apk"
(cd "$OUT_DIR/dex" && zip -q -j "$OUT_DIR/with_dex.apk" classes.dex)

# 6. Align & sign
"$BUILD_TOOLS/zipalign" -f -p 4 "$OUT_DIR/with_dex.apk" "$OUT_DIR/aligned.apk"
"$BUILD_TOOLS/apksigner" sign \
  --v4-signing-enabled false \
  --ks "$KEYSTORE" \
  --ks-pass pass:gt5charging2026 \
  --ks-key-alias gt5charging \
  --key-pass pass:gt5charging2026 \
  --out "$APK_DST" \
  "$OUT_DIR/aligned.apk"

"$BUILD_TOOLS/apksigner" verify "$APK_DST"
rm -f "$APK_DST.idsig"
chmod 0644 "$APK_DST"
rm -rf "$OUT_DIR"
ls -lh "$APK_DST"
echo "Built & signed: $APK_DST"
