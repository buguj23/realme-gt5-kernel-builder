#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_APK="$DIR/../gt5_halo_tile.apk"
BUILD="$DIR/.build"
ANDROID_JAR="${ANDROID_JAR:-/home/buguj/Android/Sdk/platforms/android-33/android.jar}"
[ -f "$ANDROID_JAR" ] || ANDROID_JAR="/opt/android-sdk/platforms/android-37.0/android.jar"

KEYSTORE="$DIR/gt5_halo_tile.keystore"
if [ ! -f "$KEYSTORE" ]; then
  keytool -genkeypair -v \
    -keystore "$KEYSTORE" \
    -storepass gt5halotile \
    -keypass gt5halotile \
    -alias gt5halo \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=GT5 Halo, OU=HaloTile, O=GT5, C=CN" >/dev/null 2>&1
fi

rm -rf "$BUILD"
mkdir -p "$BUILD/compiled_res" "$BUILD/gen" "$BUILD/classes" "$BUILD/dex"

# 1. Compile & link resources with aapt2
aapt2 compile --dir "$DIR/res" -o "$BUILD/compiled_res/res.zip"
aapt2 link \
  -I "$ANDROID_JAR" \
  --manifest "$DIR/AndroidManifest.xml" \
  --java "$BUILD/gen" \
  --min-sdk-version 31 \
  --target-sdk-version 33 \
  -o "$BUILD/unaligned.apk" \
  "$BUILD/compiled_res/res.zip"

# 2. Compile Java sources
javac -source 1.8 -target 1.8 \
  -bootclasspath "$ANDROID_JAR" \
  -d "$BUILD/classes" \
  "$BUILD/gen/com/gt5/halotile/R.java" \
  "$DIR/src/com/gt5/halotile/"*.java

# 3. DEX with d8
d8 --min-api 31 --lib "$ANDROID_JAR" --output "$BUILD/dex" \
  $(find "$BUILD/classes" -name '*.class')

# 4. Pack classes.dex into APK, zipalign, and sign (v2/v3)
(cd "$BUILD/dex" && zip -q -u "$BUILD/unaligned.apk" classes.dex)
zipalign -f 4 "$BUILD/unaligned.apk" "$BUILD/aligned.apk"
apksigner sign \
  --ks "$KEYSTORE" \
  --ks-key-alias gt5halo \
  --ks-pass pass:gt5halotile \
  --key-pass pass:gt5halotile \
  --v1-signing-enabled true \
  --v2-signing-enabled true \
  --v3-signing-enabled true \
  --out "$OUT_APK" \
  "$BUILD/aligned.apk"
apksigner verify "$OUT_APK"
rm -rf "$BUILD"
ls -lh "$OUT_APK"
