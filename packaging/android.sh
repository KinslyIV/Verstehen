#!/usr/bin/env bash
# Android app tooling: `setup`, `sdk`, `debug`, `release`, `key` (see docs/architecture/tooling.md).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export JAVA_HOME="${ANDROID_JAVA_HOME:-/usr/lib/jvm/java-21-openjdk}"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

system_image="system-images;android-36;google_apis;x86_64"
cmdline_tools_zip="commandlinetools-linux-13114758_latest.zip"
cmdline_tools_sha256="7ec965280a073311c339e571cd5de778b9975026cfcbe79f2b1cdcb1e15317ee"
key_directory="$HOME/.config/verstehen"
keystore="$key_directory/android-release.jks"
key_password_file="$key_directory/android-release.password"
key_alias="verstehen"

version() {
  python3 -c "import tomllib; print(tomllib.load(open('$root/backend/pyproject.toml','rb'))['project']['version'])"
}

require_java() {
  [ -x "$JAVA_HOME/bin/java" ] || {
    echo "Capacitor 8 needs JDK 21 at $JAVA_HOME. Install it (Arch: sudo pacman -S jdk21-openjdk) or set ANDROID_JAVA_HOME." >&2
    exit 1
  }
}

install_cmdline_tools() {
  [ -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ] && return
  local scratch
  scratch="$(mktemp -d)"
  curl -sSfL -o "$scratch/tools.zip" "https://dl.google.com/android/repository/$cmdline_tools_zip"
  echo "$cmdline_tools_sha256  $scratch/tools.zip" | sha256sum --check --quiet
  unzip -q "$scratch/tools.zip" -d "$scratch"
  mkdir -p "$ANDROID_HOME/cmdline-tools"
  rm -rf "$ANDROID_HOME/cmdline-tools/latest"
  mv "$scratch/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest"
  rm -rf "$scratch"
}

install_sdk_packages() {
  require_java
  install_cmdline_tools
  yes | sdkmanager --licenses >/dev/null || true
  sdkmanager "platform-tools" "build-tools;36.0.0" "platforms;android-36" "$@" >/dev/null
}

set_avd_option() {
  local config="${ANDROID_AVD_HOME:-$HOME/.android/avd}/$1.avd/config.ini"
  grep -v "^$2=" "$config" >"$config.new" || true
  echo "$2=$3" >>"$config.new"
  mv "$config.new" "$config"
}

create_avd() {
  local name="$1" device="$2" width="$3" height="$4" density="$5"
  if [ ! -d "${ANDROID_AVD_HOME:-$HOME/.android/avd}/$name.avd" ]; then
    echo no | avdmanager create avd --name "$name" --package "$system_image" --device "$device" >/dev/null
  fi
  set_avd_option "$name" hw.lcd.width "$width"
  set_avd_option "$name" hw.lcd.height "$height"
  set_avd_option "$name" hw.lcd.density "$density"
  set_avd_option "$name" hw.ramSize 3072
  set_avd_option "$name" hw.keyboard yes
}

build_apk() {
  local task="$1" output="$2" destination="$3"
  require_java
  cd "$root/app"
  npm run build
  npx cap sync android
  local release_version
  release_version="$(version)"
  cd android
  ./gradlew --no-daemon "-PverstehenVersion=$release_version" testDebugUnitTest "$task"
  mkdir -p "$root/dist"
  cp "$output" "$root/dist/$destination"
  echo "Wrote dist/$destination"
}

load_release_key() {
  if [ -n "${VERSTEHEN_ANDROID_KEYSTORE:-}" ]; then
    return
  fi
  if [ -f "$keystore" ] && [ -f "$key_password_file" ]; then
    export VERSTEHEN_ANDROID_KEYSTORE="$keystore"
    VERSTEHEN_ANDROID_KEYSTORE_PASSWORD="$(cat "$key_password_file")"
    export VERSTEHEN_ANDROID_KEYSTORE_PASSWORD
  else
    echo "No release key at $keystore: the release .apk will be unsigned and cannot be installed. Run make android-key." >&2
  fi
}

case "${1:-}" in
  sdk)
    install_sdk_packages
    ;;
  setup)
    install_sdk_packages "emulator" "$system_image"
    create_avd Galaxy_S24 pixel_7 1080 2340 480
    create_avd Galaxy_Tab_S9 pixel_tablet 1600 2560 320
    echo "Android SDK and the Galaxy_S24 and Galaxy_Tab_S9 virtual devices are ready."
    ;;
  debug)
    install_sdk_packages
    export PUBLIC_VERSTEHEN_EXTRA_HOSTS=10.0.2.2
    build_apk assembleDebug app/build/outputs/apk/debug/app-debug.apk "verstehen-$(version)-debug.apk"
    ;;
  release)
    install_sdk_packages
    load_release_key
    suffix=""
    [ -n "${VERSTEHEN_ANDROID_KEYSTORE:-}" ] || suffix="-unsigned"
    build_apk assembleRelease "app/build/outputs/apk/release/app-release${suffix}.apk" "verstehen-$(version)${suffix}.apk"
    ;;
  key)
    if [ -e "$keystore" ]; then
      echo "$keystore already exists; keeping it. Delete it yourself to create a new key." >&2
      exit 1
    fi
    require_java
    mkdir -p "$key_directory"
    umask 077
    openssl rand -hex 24 >"$key_password_file"
    keytool -genkeypair -keystore "$keystore" -alias "$key_alias" -keyalg RSA -keysize 4096 \
      -validity 36500 -dname "CN=Verstehen" \
      -storepass "$(cat "$key_password_file")" -keypass "$(cat "$key_password_file")"
    echo "Created $keystore and $key_password_file (keep both private and backed up)."
    echo "Add these GitHub secrets so tagged releases attach a signed .apk:"
    echo "  base64 -w0 $keystore | gh secret set ANDROID_KEYSTORE_BASE64"
    echo "  gh secret set ANDROID_KEYSTORE_PASSWORD < $key_password_file"
    echo "  gh secret set ANDROID_KEY_ALIAS --body $key_alias"
    ;;
  *)
    echo "usage: android.sh setup|sdk|debug|release|key" >&2
    exit 2
    ;;
esac
