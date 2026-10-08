# Build debug APK for 消息助手
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $Root "..\..\..")).Path

$env:JAVA_HOME = "C:\Users\dj\jdks\jdk-17"
$env:ANDROID_HOME = Join-Path $RepoRoot "android-sdk"
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$gradleBin = Join-Path $RepoRoot "gradle\gradle-8.13\bin"
$env:Path = "$gradleBin;$env:JAVA_HOME\bin;$env:ANDROID_HOME\cmdline-tools\latest\bin;$env:ANDROID_HOME\platform-tools;" + $env:Path
$env:CORDOVA_ANDROID_GRADLE_DISTRIBUTION_URL = "file:///" + ((Join-Path $RepoRoot "gradle-8.13-bin.zip") -replace '\\', '/')

Set-Location $Root
cordova build android
$apk = Join-Path $Root "platforms\android\app\build\outputs\apk\debug\app-debug.apk"
$dest = Join-Path $Root "消息助手-debug.apk"
Copy-Item $apk $dest -Force
Write-Host "APK: $dest"
