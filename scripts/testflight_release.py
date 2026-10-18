#!/usr/bin/env python3
"""Explicit archive, export, verify and upload phases for Reverse CAD TestFlight.

Uses only the Python standard library and installed Xcode tools. No credentials
are discovered, copied, embedded, or read by this script. See docs/TESTFLIGHT.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = "com.pranav.ReverseCAD"
DEFAULT_TEAM = "5B3Y68ZB2Y"
PRODUCT = "ReverseCAD"
SCHEME = "ReverseCAD"


def select_app(prelude: bool = False) -> None:
    global BUNDLE, PRODUCT, SCHEME
    BUNDLE = "com.pranavmuralitharan.prelude" if prelude else "com.pranav.ReverseCAD"
    PRODUCT = "Prelude" if prelude else "ReverseCAD"
    SCHEME = "PreludeScanner" if prelude else "ReverseCAD"



class ReleaseError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseError(message)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")


def run(command: list[str], log: Path | None = None) -> bytes:
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        # Commands contain paths/identifiers, never private key contents.
        print(f"Running {command[0]} (log: {log.relative_to(ROOT)})", flush=True)
        with log.open("xb") as stream:
            stream.write((json.dumps(command) + "\n").encode())
            stream.flush()
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        require(result.returncode == 0, f"Command failed ({result.returncode}); inspect {log}")
        return b""
    result = subprocess.run(command, cwd=ROOT, capture_output=True)
    require(result.returncode == 0, f"{command[0]} failed: {result.stderr.decode(errors='replace')[:3000]}")
    return result.stdout


def tree_manifest(path: Path) -> dict[str, str]:
    return {p.relative_to(path).as_posix(): digest(p)
            for p in sorted(path.rglob("*")) if p.is_file()}


def paths(args: argparse.Namespace) -> tuple[Path, Path]:
    name = f"{PRODUCT.lower()}-release-{args.version}-{args.build}" if PRODUCT != "ReverseCAD" else f"release-{args.version}-{args.build}"
    return ROOT / "var/testflight" / name, ROOT / "reports/testflight" / name


def load_release(args: argparse.Namespace) -> tuple[Path, Path, dict]:
    release, reports = paths(args)
    require((release / "release.json").is_file(), "Archive this version/build first.")
    metadata = json.loads((release / "release.json").read_text())
    require(metadata["version"] == args.version and metadata["build"] == args.build,
            "Release metadata does not match the requested version/build.")
    require(metadata["bundle_id"] == BUNDLE, "Release belongs to another app.")
    require(metadata["team"] == args.team, "Team does not match the archived release.")
    return release, reports, metadata


def check_archive(release: Path, reports: Path) -> None:
    receipt_path = reports / "archive.json"
    require(receipt_path.is_file(), "No successful archive receipt; preserve the failed attempt and use a new build number.")
    receipt = json.loads(receipt_path.read_text())
    require(json.loads((release / "release.json").read_text()) == receipt["metadata"],
            "Release metadata changed after archive creation.")
    require(tree_manifest(release / f"{PRODUCT}.xcarchive") == receipt["archive_files_sha256"],
            "Archive changed after creation; refusing to export/upload.")


def export_options(metadata: dict, destination: str) -> dict:
    return {
        "method": "app-store-connect", "destination": destination,
        "teamID": metadata["team"], "signingStyle": "manual",
        "signingCertificate": metadata["identity"],
        "provisioningProfiles": {BUNDLE: metadata["profile_uuid"]},
        "testFlightInternalTestingOnly": True,
        "manageAppVersionAndBuildNumber": False,
        "stripSwiftSymbols": True, "uploadSymbols": True,
        "generateAppStoreInformation": True,
    }


def archive(args: argparse.Namespace) -> None:
    release, reports = paths(args)
    require(not release.exists(), f"Immutable release already exists: {release}. Use a new build number.")
    require(not reports.exists(), f"Reports already exist: {reports}. Use a new build number.")
    require(shutil.which("xcodegen") is not None, "Install XcodeGen and run ./scripts/bootstrap.sh first.")
    require((ROOT / "ios/ReverseCAD/SampleScan/manifest.json").is_file(),
            "Bundled sample scan missing; run ./scripts/bootstrap.sh first.")
    release.mkdir(parents=True)
    reports.mkdir(parents=True)
    metadata = {
        "bundle_id": BUNDLE, "version": args.version, "build": args.build,
        "team": args.team, "profile_uuid": args.profile_uuid,
        "identity": args.identity, "created_at": now(),
        "distribution": "app-store-connect", "testflight_internal_only": True,
        "xcode_version": run(["xcodebuild", "-version"]).decode().strip(),
    }
    if PRODUCT == "Prelude":
        config = ROOT / "ios/PrivateResources/PreludeJevConfig.plist"
        require(config.is_file(), "Prepare the personal direct-Jev resource with configure_prelude_jev.py first.")
        key = plistlib.loads(config.read_bytes()).get("apiKey")
        require(isinstance(key, str) and bool(key.strip()), "Personal Jev key is empty.")
        metadata["direct_jev_config_sha256"] = digest(config)
    write_json(release / "release.json", metadata)
    run(["xcodegen", "generate", "--spec", "ios/project.yml"], reports / "xcodegen.log")
    command = [
        "xcodebuild", "-project", "ios/ReverseCAD.xcodeproj", "-scheme", SCHEME,
        "-configuration", "Release", "-destination", "generic/platform=iOS",
        "-archivePath", str(release / f"{PRODUCT}.xcarchive"),
        "-derivedDataPath", str(release / "DerivedData"),
        "-resultBundlePath", str(reports / "archive.xcresult"),
        "-hideShellScriptEnvironment", "CODE_SIGN_STYLE=Manual",
        f"DEVELOPMENT_TEAM={args.team}", f"CODE_SIGN_IDENTITY={args.identity}",
        f"REVERSECAD_PROFILE_{SCHEME}={args.profile_uuid}",
        "PROVISIONING_PROFILE_SPECIFIER=$(REVERSECAD_PROFILE_$(TARGET_NAME))",
        f"PRODUCT_BUNDLE_IDENTIFIER={BUNDLE}", f"MARKETING_VERSION={args.version}", f"CURRENT_PROJECT_VERSION={args.build}",
        "CODE_SIGNING_ALLOWED=YES", "archive",
    ]
    run(command, reports / "archive.log")
    app = release / f"{PRODUCT}.xcarchive/Products/Applications/{PRODUCT}.app"
    require(app.is_dir(), "Xcode returned success without ReverseCAD.app in the archive.")
    info = plistlib.loads((app / "Info.plist").read_bytes())
    require(info.get("CFBundleIdentifier") == BUNDLE, "Wrong archived bundle identifier.")
    require(info.get("CFBundleVersion") == args.build and info.get("CFBundleShortVersionString") == args.version,
            "Archived version/build mismatch.")
    write_json(reports / "archive.json", {
        "status": "passed", "completed_at": now(), "metadata": metadata,
        "archive_files_sha256": tree_manifest(release / f"{PRODUCT}.xcarchive"),
    })
    print(f"Archived {args.version} ({args.build}). Next: export, then verify. Nothing uploaded.")


def export(args: argparse.Namespace) -> None:
    release, reports, metadata = load_release(args)
    check_archive(release, reports)
    destination = release / "export"
    require(not destination.exists() and not (reports / "export.log").exists(),
            "Export attempt already exists. Preserve it and use a new build number rather than overwrite.")
    options = release / "ExportOptions.plist"
    with options.open("xb") as stream:
        plistlib.dump(export_options(metadata, "export"), stream)
    run(["xcodebuild", "-exportArchive", "-archivePath", str(release / f"{PRODUCT}.xcarchive"),
         "-exportPath", str(destination), "-exportOptionsPlist", str(options)], reports / "export.log")
    ipas = list(destination.glob("*.ipa"))
    require(len(ipas) == 1, f"Expected one exported IPA, found {len(ipas)}.")
    write_json(reports / "export.json", {
        "status": "passed", "completed_at": now(), "ipa": str(ipas[0].relative_to(ROOT)),
        "ipa_sha256": digest(ipas[0]), "export_files_sha256": tree_manifest(destination),
    })
    print(f"Exported {ipas[0]}. Next: verify. Nothing uploaded.")


def read_plist_command(command: list[str]) -> dict:
    raw = run(command)
    begin = raw.find(b"<?xml")
    if begin < 0:
        begin = raw.find(b"bplist")
    require(begin >= 0, f"{command[0]} did not return a property list.")
    return plistlib.loads(raw[begin:])


def verify_ipa(ipa: Path, metadata: dict) -> dict:
    """Inspect the exported bytes, not project source or a development build."""
    with tempfile.TemporaryDirectory(prefix="reversecad-verify-") as temporary:
        folder = Path(temporary)
        with zipfile.ZipFile(ipa) as package:
            total = 0
            seen: set[str] = set()
            for entry in package.infolist():
                name = PurePosixPath(entry.filename)
                require(not name.is_absolute() and ".." not in name.parts and "\\" not in entry.filename,
                        "Unsafe IPA member path.")
                require(entry.filename not in seen, "Duplicate IPA member path.")
                seen.add(entry.filename)
                require(not stat.S_ISLNK(entry.external_attr >> 16), "Unexpected symlink in iOS IPA.")
                total += entry.file_size
                require(total < 8 * 1024**3, "IPA exceeds extraction size limit.")
        # ditto preserves executable bits needed for signature verification.
        run(["ditto", "-x", "-k", str(ipa), str(folder)])
        apps = list((folder / "Payload").glob("*.app"))
        require(len(apps) == 1, "IPA must contain exactly one top-level application.")
        app = apps[0]
        info = plistlib.loads((app / "Info.plist").read_bytes())
        require(info.get("CFBundleIdentifier") == BUNDLE, "IPA bundle identifier mismatch.")
        if metadata.get("direct_jev_config_sha256"):
            config = app / "PreludeJevConfig.plist"
            require(BUNDLE == "com.pranavmuralitharan.prelude" and metadata.get("testflight_internal_only") is True,
                    "Personal Jev configuration is restricted to the internal Prelude build.")
            require(config.is_file() and digest(config) == metadata["direct_jev_config_sha256"],
                    "IPA is missing the configured personal Jev resource or its bytes differ.")
        require(info.get("CFBundleShortVersionString") == metadata["version"], "IPA marketing version mismatch.")
        require(info.get("CFBundleVersion") == metadata["build"], "IPA build number mismatch.")
        require(info.get("CFBundlePackageType") == "APPL", "IPA is not an application bundle.")
        require(info.get("CFBundleSupportedPlatforms") == ["iPhoneOS"], "IPA is not an iPhone device build.")
        require(info.get("DTPlatformName") == "iphoneos", "IPA platform metadata is not iphoneos.")
        minimum_os = str(info.get("MinimumOSVersion", ""))
        require(re.fullmatch(r"\d+(?:\.\d+){0,2}", minimum_os) is not None and int(minimum_os.split(".")[0]) >= 17,
                "MinimumOSVersion missing or below iOS 17.")
        require(1 in info.get("UIDeviceFamily", []), "IPA does not support iPhone.")
        require(info.get("ITSAppUsesNonExemptEncryption") is False, "Encryption declaration is missing or changed; review export compliance.")
        for key in ("NSCameraUsageDescription", "NSMotionUsageDescription", "NSLocalNetworkUsageDescription"):
            require(isinstance(info.get(key), str) and bool(info[key].strip()), f"Missing purpose string: {key}")
        orientations = info.get("UISupportedInterfaceOrientations", [])
        require("UIInterfaceOrientationPortrait" in orientations, "Missing iPhone portrait orientation.")
        if 2 in info.get("UIDeviceFamily", []) and not info.get("UIRequiresFullScreen", False):
            require(set(info.get("UISupportedInterfaceOrientations~ipad", [])) >= {
                "UIInterfaceOrientationPortrait", "UIInterfaceOrientationPortraitUpsideDown",
                "UIInterfaceOrientationLandscapeLeft", "UIInterfaceOrientationLandscapeRight"},
                "iPad multitasking requires all four interface orientations.")
        primary = info.get("CFBundleIcons", {}).get("CFBundlePrimaryIcon", {})
        require(primary.get("CFBundleIconName") == "AppIcon" and primary.get("CFBundleIconFiles"),
                "Compiled AppIcon metadata missing.")
        require((app / "Assets.car").is_file(), "Compiled asset catalog missing.")
        require(any(app.glob("AppIcon*.png")), "Compiled application icon pixels missing.")
        privacy_path = app / "PrivacyInfo.xcprivacy"
        require(privacy_path.is_file(), "PrivacyInfo.xcprivacy missing from IPA.")
        privacy = plistlib.loads(privacy_path.read_bytes())
        require(privacy.get("NSPrivacyTracking") is False, "Unexpected or missing privacy tracking declaration.")
        if "NSPrivacyCollectedDataTypes" in privacy:
            require(isinstance(privacy["NSPrivacyCollectedDataTypes"], list),
                    "Privacy collection declarations must be an array when present.")
        accessed = privacy.get("NSPrivacyAccessedAPITypes")
        require(isinstance(accessed, list) and all(isinstance(item, dict) for item in accessed),
                "Privacy manifest missing required-reason API declarations.")
        expected_reasons = {
            "NSPrivacyAccessedAPICategoryUserDefaults": {"CA92.1"},
            "NSPrivacyAccessedAPICategoryFileTimestamp": {"C617.1", "3B52.1"},
            "NSPrivacyAccessedAPICategoryDiskSpace": {"E174.1"},
            "NSPrivacyAccessedAPICategorySystemBootTime": {"35F9.1"},
        }
        actual_reasons = {}
        for item in accessed:
            category = item.get("NSPrivacyAccessedAPIType")
            reasons = item.get("NSPrivacyAccessedAPITypeReasons")
            require(isinstance(category, str) and isinstance(reasons, list)
                    and all(isinstance(reason, str) for reason in reasons),
                    "Malformed privacy required-reason declaration.")
            require(category not in actual_reasons, "Duplicate privacy API category.")
            actual_reasons[category] = set(reasons)
        require(all(actual_reasons.get(category, set()) >= reasons for category, reasons in expected_reasons.items()),
                "Privacy manifest does not declare this release's reviewed API reasons; see docs/PRIVACY_RELEASE.md.")

        run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
        details_result = subprocess.run(["codesign", "-d", "--verbose=4", str(app)], capture_output=True)
        require(details_result.returncode == 0, "Cannot inspect code signature.")
        details = (details_result.stdout + details_result.stderr).decode(errors="replace")
        require(f"TeamIdentifier={metadata['team']}\n" in details, "Code signature team mismatch.")
        require(re.search(r"^Authority=(?:Apple Distribution|iPhone Distribution):", details, re.M) is not None,
                "IPA is not signed with an Apple distribution certificate.")
        entitlements = read_plist_command(["codesign", "-d", "--entitlements", ":-", str(app)])
        expected_app_id = metadata["team"] + "." + BUNDLE
        require(entitlements.get("application-identifier") == expected_app_id, "Signed application identifier mismatch.")
        require(entitlements.get("com.apple.developer.team-identifier") == metadata["team"], "Signed entitlement team mismatch.")
        require(entitlements.get("get-task-allow") is False, "Debugger entitlement must be explicitly false.")
        require(entitlements.get("beta-reports-active") is True, "Signed beta-reports-active entitlement missing.")
        profile_path = app / "embedded.mobileprovision"
        require(profile_path.is_file(), "Embedded distribution provisioning profile missing.")
        profile = read_plist_command(["security", "cms", "-D", "-i", str(profile_path)])
        require(profile.get("UUID") == metadata["profile_uuid"], "Embedded profile UUID mismatch.")
        require(profile.get("TeamIdentifier") == [metadata["team"]], "Embedded profile team mismatch.")
        require("ProvisionedDevices" not in profile and not profile.get("ProvisionsAllDevices", False),
                "Embedded profile is development, ad hoc, or enterprise, not App Store distribution.")
        profile_entitlements = profile.get("Entitlements", {})
        require(profile_entitlements.get("application-identifier") == expected_app_id,
                "Embedded profile must use the explicit ReverseCAD App ID, not a wildcard.")
        require(profile_entitlements.get("get-task-allow") is False, "Profile permits debugger attachment.")
        require(profile_entitlements.get("beta-reports-active") is True, "Profile is not enabled for TestFlight.")
        expiry = profile.get("ExpirationDate")
        require(isinstance(expiry, dt.datetime), "Provisioning profile has no expiration date.")
        expiry = expiry.replace(tzinfo=dt.timezone.utc) if expiry.tzinfo is None else expiry
        require(expiry > dt.datetime.now(dt.timezone.utc), "Provisioning profile is expired.")
        prefix = folder / "signing-cert-"
        run(["codesign", "-d", f"--extract-certificates={prefix}", str(app)])
        certificate = folder / "signing-cert-0"
        require(certificate.is_file(), "Signing certificate extraction failed.")
        certificate_hash = digest(certificate)
        require(any(hashlib.sha256(cert).hexdigest() == certificate_hash for cert in profile.get("DeveloperCertificates", [])),
                "Actual signing certificate is not authorized by the embedded profile.")
        run(["openssl", "x509", "-inform", "DER", "-in", str(certificate), "-checkend", "0", "-noout"])
        executable_name = info.get("CFBundleExecutable", "")
        require(executable_name and Path(executable_name).name == executable_name, "Invalid bundle executable name.")
        if BUNDLE == "com.pranavmuralitharan.prelude":
            binary = (app / executable_name).read_bytes()
            require(not any(marker in binary for marker in [b"BackSparseTimeOfFlight", b"SRStart", b"SRStop", b"SRFrameMetadata"]), "Private research symbols found in distribution executable.")
        architectures = run(["lipo", "-archs", str(app / executable_name)]).decode().strip().split()
        require("arm64" in architectures and not {"x86_64", "i386"}.intersection(architectures),
                "IPA executable lacks arm64 or contains simulator architectures.")
        return {
            "status": "passed", "verified_at": now(), "ipa_sha256": digest(ipa),
            "ipa_size_bytes": ipa.stat().st_size, "bundle_id": BUNDLE,
            "version": info["CFBundleShortVersionString"], "build": info["CFBundleVersion"],
            "minimum_ios": minimum_os, "architectures": architectures, "team": metadata["team"],
            "profile_uuid": profile["UUID"], "profile_expires_at": expiry.isoformat(),
            "signing_certificate_sha256": certificate_hash,
            "embedded_profile_sha256": digest(profile_path),
            "privacy_manifest_sha256": digest(privacy_path),
            "app_files_sha256": tree_manifest(app),
            "checks": ["distribution_signature", "certificate_profile_match", "unexpired_explicit_app_store_profile",
                       "beta_reports_active", "debugger_disabled", "no_device_list", "version_build_bundle_team",
                       "device_arm64", "app_icon", "privacy_manifest", "purpose_strings", "orientation_metadata"],
            "boundaries": ["Apple processing and TestFlight availability are not established by local verification",
                           "Real-device sensing and printed fit remain unverified"],
        }


def verified_export(release: Path, reports: Path, metadata: dict) -> tuple[Path, dict]:
    receipt_path = reports / "export.json"
    require(receipt_path.is_file(), "Export this archive first.")
    receipt = json.loads(receipt_path.read_text())
    ipa = ROOT / receipt["ipa"]
    require(ipa.is_file() and digest(ipa) == receipt["ipa_sha256"], "Exported IPA is missing or changed.")
    require(tree_manifest(release / "export") == receipt["export_files_sha256"], "Export directory changed after export.")
    return ipa, verify_ipa(ipa, metadata)


def verify(args: argparse.Namespace) -> None:
    release, reports, metadata = load_release(args)
    check_archive(release, reports)
    ipa, report = verified_export(release, reports, metadata)
    # Verification can be repeated; preserve each receipt rather than overwrite.
    suffix = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    path = reports / f"verify-{suffix}.json"
    write_json(path, report)
    print(f"Verified {ipa.name}: {report['ipa_sha256']}\nReport: {path}\nNothing uploaded.")


def upload(args: argparse.Namespace) -> None:
    release, reports, metadata = load_release(args)
    check_archive(release, reports)
    _, verification = verified_export(release, reports, metadata)
    key = args.key_path.expanduser().resolve()
    require(key.is_file(), "App Store Connect authentication key path does not exist.")
    require(stat.S_IMODE(key.stat().st_mode) & 0o077 == 0, "Authentication key must not be accessible to group/others (chmod 600).")
    require(not (reports / "upload.log").exists(), "An upload attempt already exists. Inspect App Store Connect before retrying; do not duplicate uploads.")
    options = release / "UploadOptions.plist"
    with options.open("xb") as stream:
        plistlib.dump(export_options(metadata, "upload"), stream)
    write_json(reports / "pre-upload-verification.json", verification)
    # Xcode re-exports this unchanged archive for upload. The local verified IPA
    # is retained, but do not claim its hash identifies Apple's re-exported bytes.
    run(["xcodebuild", "-exportArchive", "-archivePath", str(release / f"{PRODUCT}.xcarchive"),
         "-exportPath", str(release / "upload"), "-exportOptionsPlist", str(options),
         "-authenticationKeyPath", str(key), "-authenticationKeyID", args.key_id,
         "-authenticationKeyIssuerID", args.issuer_id], reports / "upload.log")
    write_json(reports / "upload.json", {
        "status": "xcode_upload_succeeded", "completed_at": now(), "bundle_id": BUNDLE,
        "version": metadata["version"], "build": metadata["build"],
        "verified_local_ipa_sha256": verification["ipa_sha256"],
        "note": "Xcode uploaded a re-export of the verified unchanged archive. Check Apple processing and internal tester availability separately.",
    })
    print("Xcode reports upload succeeded. App Store Connect processing and internal tester access still require confirmation.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="phase", required=True)
    for phase in ("archive", "export", "verify", "upload"):
        sub = subparsers.add_parser(phase)
        sub.add_argument("--version", required=True, help="Marketing version, e.g. 1.0")
        sub.add_argument("--build", required=True, help="Unique positive integer build number")
        sub.add_argument("--team", default=DEFAULT_TEAM)
        sub.add_argument("--prelude", action="store_true", help="Use the isolated public-API Prelude scanner target")
        if phase == "archive":
            sub.add_argument("--profile-uuid", required=True, help="Installed explicit App Store distribution profile UUID")
            sub.add_argument("--identity", required=True, help="Installed Apple Distribution identity name or SHA-1")
        if phase == "upload":
            sub.add_argument("--key-path", type=Path, required=True, help="Path to existing App Store Connect .p8 key; never its contents")
            sub.add_argument("--key-id", required=True)
            sub.add_argument("--issuer-id", required=True)
    args = parser.parse_args()
    select_app(args.prelude)
    try:
        require(re.fullmatch(r"\d+\.\d+(?:\.\d+)?", args.version) is not None, "Version must be numeric major.minor[.patch].")
        require(re.fullmatch(r"[1-9]\d*", args.build) is not None, "Build must be a positive integer.")
        require(re.fullmatch(r"[A-Z0-9]{10}", args.team) is not None, "Team must be a 10-character Apple team identifier.")
        if args.phase == "archive":
            require(re.fullmatch(r"[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}", args.profile_uuid) is not None,
                    "A provisioning profile UUID is required, not a profile name.")
            require(bool(args.identity.strip()), "Distribution signing identity is required.")
        {"archive": archive, "export": export, "verify": verify, "upload": upload}[args.phase](args)
        return 0
    except (ReleaseError, OSError, ValueError, KeyError, plistlib.InvalidFileException, zipfile.BadZipFile) as error:
        print(f"Release stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
