#!/usr/bin/env python3
"""Upload one verified Reverse CAD IPA using Apple's official Build Upload API.

Uses Apple HTTPS Date for JWT time without changing the Mac clock. API tokens,
private keys, upload URLs and upload headers are never written to reports.
Reference: https://developer.apple.com/documentation/appstoreconnectapi/build-uploads
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import testflight_release as release_tools

BASE = "https://api.appstoreconnect.apple.com"
Error = release_tools.ReleaseError
require = release_tools.require


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def safe_text(value: object) -> str:
    text = re.sub(r"https?://\S+", "[URL omitted]", str(value))
    return re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[token omitted]", text)[:2000]


def safe_report(value):
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, dict):
        return {key: safe_report(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_report(item) for item in value]
    return value


def resource_id(value: object) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9-]+", value) is not None,
            "Invalid Apple resource identifier.")
    return value


class Client:
    def __init__(self, key_path: Path, key_id: str, issuer_id: str):
        require(key_path.is_file(), "API key file does not exist.")
        require(stat.S_IMODE(key_path.stat().st_mode) & 0o077 == 0,
                "API key file must be private (chmod 600).")
        self.key_path, self.key_id, self.issuer_id = key_path, key_id, issuer_id
        self.opener = urllib.request.build_opener(NoRedirect)
        self.token, self.expiry = "", 0
        self.clock_offset = self.apple_clock_offset()

    def apple_clock_offset(self) -> float:
        started = time.time()
        request = urllib.request.Request(BASE + "/v1/apps", method="HEAD")
        try:
            response = self.opener.open(request, timeout=30)
        except urllib.error.HTTPError as error:
            require(error.code == 401, f"Unexpected clock-probe HTTP status {error.code}.")
            response = error
        with response:
            require(response.geturl() == BASE + "/v1/apps", "Apple clock probe changed origin.")
            require(bool(response.headers.get("Date")), "Apple response has no Date header.")
            server = parsedate_to_datetime(response.headers["Date"]).timestamp()
        return server - (started + time.time()) / 2

    def jwt(self) -> str:
        timestamp = int(time.time() + self.clock_offset)
        if self.token and timestamp < self.expiry - 30:
            return self.token
        encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=")
        part = lambda value: encode(json.dumps(value, separators=(",", ":")).encode())
        self.expiry = timestamp + 300
        message = part({"alg": "ES256", "kid": self.key_id, "typ": "JWT"}) + b"." + part({
            "iss": self.issuer_id, "iat": timestamp, "exp": self.expiry, "aud": "appstoreconnect-v1"})
        signed = subprocess.run(["/usr/bin/openssl", "dgst", "-sha256", "-sign", str(self.key_path)],
                                input=message, capture_output=True)
        require(signed.returncode == 0, "JWT signing failed; private key/error output omitted.")
        der = signed.stdout
        require(len(der) >= 8 and der[0] == 0x30 and der[1] == len(der) - 2,
                "Invalid ES256 signature structure.")
        offset, integers = 2, []
        for _ in range(2):
            require(offset + 2 <= len(der) and der[offset] == 2, "Invalid ES256 signature integer.")
            length = der[offset + 1]
            require(offset + 2 + length <= len(der), "Truncated ES256 signature.")
            value = der[offset + 2:offset + 2 + length].lstrip(b"\0")
            require(0 < len(value) <= 32, "Invalid ES256 component size.")
            integers.append(value.rjust(32, b"\0"))
            offset += 2 + length
        require(offset == len(der), "Unexpected ES256 signature remainder.")
        self.token = (message + b"." + encode(b"".join(integers))).decode()
        return self.token

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        # No arbitrary URLs, redirects, or caller-provided authentication headers.
        require(re.fullmatch(r"/v1/(?:apps|buildUploads|buildUploadFiles)(?:/[A-Za-z0-9-]+){0,2}", path) is not None,
                "Unsupported App Store Connect API path.")
        require(method in {"GET", "POST", "PATCH"}, "Unsupported API method.")
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        request = urllib.request.Request(BASE + path, method=method, data=data, headers={
            "Authorization": "Bearer " + self.jwt(), "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=45) as response:
                require(response.geturl() == BASE + path, "API response changed origin.")
                raw = response.read(8 * 1024 * 1024 + 1)
                require(len(raw) <= 8 * 1024 * 1024, "Oversized Apple API response.")
                return json.loads(raw)
        except urllib.error.HTTPError as error:
            try:
                body = json.loads(error.read(128 * 1024))
                details = "; ".join(safe_text(item.get("detail", item.get("code", "")))
                                    for item in body.get("errors", [])[:4])
            except (ValueError, AttributeError, TypeError):
                details = "response body omitted"
            raise Error(f"Apple API {method} returned HTTP {error.code}: {details}") from None
        except urllib.error.URLError:
            raise Error("Apple API connection failed; an attempted write may have succeeded. Inspect saved progress before retrying.") from None


def validate_operations(operations: list, size: int) -> list[dict]:
    require(isinstance(operations, list) and bool(operations), "Apple returned no upload operations.")
    ordered = sorted(operations, key=lambda item: item.get("offset", -1))
    cursor = 0
    for operation in ordered:
        require(operation.get("method") == "PUT", "Only Apple-returned PUT upload operations are supported.")
        require(type(operation.get("offset")) is int and operation["offset"] == cursor,
                "Upload parts overlap or leave a gap.")
        length = operation.get("length")
        require(type(length) is int and 0 < length <= 256 * 1024 * 1024,
                "Unsupported upload part size (maximum 256 MiB).")
        cursor += length
        parsed = urllib.parse.urlsplit(operation.get("url", ""))
        require(parsed.scheme == "https" and parsed.hostname and "." in parsed.hostname
                and not parsed.username and not parsed.password and not parsed.fragment
                and parsed.port in {None, 443}, "Unsafe Apple-returned upload URL.")
        require(not parsed.hostname.endswith((".local", ".localhost")), "Local upload destinations are forbidden.")
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            raise Error("IP-literal upload destinations are forbidden.")
        for header in operation.get("requestHeaders", []):
            name, value = header.get("name"), header.get("value")
            require(isinstance(name, str) and isinstance(value, str)
                    and re.fullmatch(r"[A-Za-z0-9-]+", name) is not None
                    and "\r" not in value and "\n" not in value, "Malformed upload header.")
            require(name.lower() not in {"authorization", "cookie", "proxy-authorization", "host"},
                    "Unexpected credential/host header in upload operation.")
    require(cursor == size, "Upload operations do not cover the exact verified IPA size.")
    return ordered


def put_part(operation: dict, data: bytes) -> None:
    # These signed URLs come only from the authenticated Apple API response.
    # Separate opener/request guarantees the ASC JWT never reaches storage.
    headers = {item["name"]: item["value"] for item in operation.get("requestHeaders", [])}
    if any(name.lower() == "content-length" for name in headers):
        require(all(int(value) == len(data) for name, value in headers.items() if name.lower() == "content-length"),
                "Apple upload Content-Length does not match the selected bytes.")
    request = urllib.request.Request(operation["url"], data=data, method="PUT", headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=120) as response:
            require(200 <= response.status < 300, "Upload storage returned a non-success status.")
            response.read(1024)
    except urllib.error.HTTPError as error:
        raise Error(f"Upload storage returned HTTP {error.code}; URL and response body omitted.") from None
    except urllib.error.URLError:
        raise Error("Upload storage connection failed; signed URL omitted. Resume rechecks Apple state.") from None


def snapshot(path: Path, state: dict) -> None:
    state["updated_at_host_utc"] = datetime.now(timezone.utc).isoformat()
    saved = safe_report(state)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(saved, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    with path.with_name("api-upload-events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(saved, separators=(",", ":")) + "\n")


def check_server_file_checksum(attributes: dict, sha256: str, md5: str) -> str:
    """Compare a returned full-file checksum if Apple provides one.

    The optional checksum request representation is not specified in Apple's
    schema. We do not send it. Accept hex/base64 encodings only when they decode
    to our independently computed file digest; never treat absent values as a
    server-side checksum confirmation.
    """
    checksums = attributes.get("sourceFileChecksums") or {}
    file_checksum = checksums.get("file") or {}
    value = file_checksum.get("hash")
    if value is None:
        return "not_returned"
    algorithm = file_checksum.get("algorithm")
    require(algorithm in {"MD5", "SHA_256"}, "Apple returned an unsupported full-file checksum algorithm.")
    expected = md5 if algorithm == "MD5" else sha256
    require(isinstance(value, str) and (value.lower() == expected
            or value == base64.b64encode(bytes.fromhex(expected)).decode()),
            "Apple's returned full-file checksum does not match the verified IPA.")
    return "matched_" + algorithm.lower()


def upload(args: argparse.Namespace, client: Client) -> None:
    release, reports, metadata = release_tools.load_release(args)
    release_tools.check_archive(release, reports)
    ipa, verification = release_tools.verified_export(release, reports, metadata)
    md5 = hashlib.md5()
    with ipa.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            md5.update(block)
    local_md5 = md5.hexdigest()
    require(metadata.get("testflight_internal_only") is True, "Expected an internal-only Xcode export.")
    require(not (reports / "upload.log").exists(), "An Xcode upload was attempted; reconcile it in Apple before using another uploader.")
    app = client.request("GET", "/v1/apps/" + args.app_id)["data"]
    require(app["id"] == args.app_id and app["attributes"]["bundleId"] == release_tools.BUNDLE,
            "Apple app record does not match com.pranav.ReverseCAD.")
    progress = reports / "api-upload-progress.json"
    if progress.exists():
        require(args.resume, "An API upload attempt exists. Inspect it, then explicitly pass --resume.")
        state = json.loads(progress.read_text())
        require(all(state.get(key) == value for key, value in {
            "app_id": args.app_id, "ipa_sha256": verification["ipa_sha256"],
            "version": args.version, "build": args.build}.items()), "Resume release identity mismatch.")
        require(state.get("build_upload_id"), "Build creation was uncertain; inspect Apple before creating another upload.")
    else:
        require(not args.resume, "There is no saved API upload to resume.")
        state = {"app_id": args.app_id, "bundle_id": release_tools.BUNDLE,
                 "version": args.version, "build": args.build, "ipa_sha256": verification["ipa_sha256"],
                 "ipa_size_bytes": verification["ipa_size_bytes"], "phase": "creating_build_upload",
                 "clock_offset_seconds": round(client.clock_offset, 3), "completed_parts": []}
        snapshot(progress, state)
        created = client.request("POST", "/v1/buildUploads", {"data": {
            "type": "buildUploads", "attributes": {"cfBundleShortVersionString": args.version,
                "cfBundleVersion": args.build, "platform": "IOS"},
            "relationships": {"app": {"data": {"type": "apps", "id": args.app_id}}}}})["data"]
        state.update(build_upload_id=resource_id(created["id"]), phase="build_upload_created")
        snapshot(progress, state)
    build_id = resource_id(state["build_upload_id"])
    state["ipa_md5"] = local_md5
    remote = client.request("GET", "/v1/buildUploads/" + build_id)["data"]
    attributes = remote["attributes"]
    require(attributes.get("cfBundleVersion") == args.build and attributes.get("cfBundleShortVersionString") == args.version,
            "Apple build upload version mismatch.")
    remote_state = attributes.get("state", {})
    if remote_state.get("state") in {"COMPLETE", "PROCESSING", "FAILED"}:
        state.update(phase="apple_" + remote_state["state"].lower(), apple_state=remote_state)
        snapshot(progress, state)
        require(remote_state["state"] != "FAILED", "Apple build processing failed; inspect the saved state report.")
        print(f"Apple build upload {build_id}: {remote_state['state']}. Tester access is a separate step.")
        return
    if state.get("build_upload_file_id"):
        file_data = client.request("GET", "/v1/buildUploadFiles/" + resource_id(state["build_upload_file_id"]))["data"]
    else:
        require(state["phase"] != "creating_file_reservation",
                "File reservation was uncertain; inspect Apple before making another reservation.")
        state["phase"] = "creating_file_reservation"
        snapshot(progress, state)
        file_data = client.request("POST", "/v1/buildUploadFiles", {"data": {
            "type": "buildUploadFiles", "attributes": {"assetType": "ASSET", "fileName": ipa.name,
                "fileSize": ipa.stat().st_size, "uti": "com.apple.ipa"},
            "relationships": {"buildUpload": {"data": {"type": "buildUploads", "id": build_id}}}}})["data"]
        state.update(build_upload_file_id=resource_id(file_data["id"]), phase="file_reserved")
        snapshot(progress, state)
    file_id = resource_id(state["build_upload_file_id"])
    file_attributes = file_data["attributes"]
    require(file_attributes["fileSize"] == ipa.stat().st_size and file_attributes["fileName"] == ipa.name,
            "Apple file reservation does not match the verified IPA.")
    state["server_file_checksum"] = check_server_file_checksum(file_attributes, verification["ipa_sha256"], local_md5)
    file_state = file_attributes.get("assetDeliveryState", {}).get("state")
    if file_state not in {"COMPLETE", "UPLOAD_COMPLETE"}:
        require(file_state != "FAILED", "Apple file delivery failed; inspect Apple before retrying.")
        operations = validate_operations(file_attributes.get("uploadOperations"), ipa.stat().st_size)
        # A resumed PUT is safe for the same immutable byte range. Re-send all
        # returned operations rather than trusting stale local chunk receipts.
        with ipa.open("rb") as stream:
            for index, operation in enumerate(operations):
                stream.seek(operation["offset"])
                data = stream.read(operation["length"])
                require(len(data) == operation["length"], "IPA changed during upload.")
                put_part(operation, data)
                part = {"index": index, "offset": operation["offset"], "length": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()}
                state["completed_parts"] = [item for item in state["completed_parts"] if item["index"] != index] + [part]
                state["phase"] = "uploading_bytes"
                snapshot(progress, state)
                print(f"Uploaded part {index + 1}/{len(operations)} ({len(data)} bytes).", flush=True)
        require(release_tools.digest(ipa) == verification["ipa_sha256"], "IPA changed during upload; refusing commit.")
        state["phase"] = "committing_file"
        snapshot(progress, state)
        committed = client.request("PATCH", "/v1/buildUploadFiles/" + file_id, {"data": {
            "type": "buildUploadFiles", "id": file_id, "attributes": {"uploaded": True}}})["data"]
        state["server_file_checksum"] = check_server_file_checksum(
            committed["attributes"], verification["ipa_sha256"], local_md5)
        file_state = committed["attributes"].get("assetDeliveryState", {}).get("state")
    state.update(phase="file_committed", apple_file_state=file_state)
    snapshot(progress, state)
    remote = client.request("GET", "/v1/buildUploads/" + build_id)["data"]
    state["apple_state"] = remote["attributes"].get("state", {})
    state["phase"] = "apple_" + state["apple_state"].get("state", "pending").lower()
    snapshot(progress, state)
    require(state["apple_state"].get("state") != "FAILED", "Apple processing failed; inspect saved progress.")
    print(f"Committed verified IPA. Apple upload ID: {build_id}; state: {state['apple_state'].get('state', 'pending')}.\n"
          "Run status to check processing. Internal tester access and build audience still require verification.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "upload", "status"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--team", default=release_tools.DEFAULT_TEAM)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--key-path", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--issuer-id", required=True)
    parser.add_argument("--resume", action="store_true", help="Resume only the existing recorded API upload")
    args = parser.parse_args()
    try:
        require(re.fullmatch(r"\d+\.\d+(?:\.\d+)?", args.version) is not None, "Invalid marketing version.")
        require(re.fullmatch(r"[1-9]\d*", args.build) is not None, "Invalid build number.")
        require(re.fullmatch(r"\d+", args.app_id) is not None, "Apple app ID must be numeric.")
        require(re.fullmatch(r"[A-Z0-9]{10}", args.key_id) is not None, "Invalid key ID.")
        require(re.fullmatch(r"[A-Fa-f0-9-]{36}", args.issuer_id) is not None, "Invalid issuer ID.")
        client = Client(args.key_path.expanduser().resolve(), args.key_id, args.issuer_id)
        if args.command == "upload":
            upload(args, client)
        else:
            app = client.request("GET", "/v1/apps/" + args.app_id)["data"]
            require(app["attributes"]["bundleId"] == release_tools.BUNDLE, "Apple app bundle identifier mismatch.")
            output = {"app_id": args.app_id, "bundle_id": release_tools.BUNDLE,
                      "clock_offset_seconds": round(client.clock_offset, 3)}
            if args.command == "check":
                release, reports, metadata = release_tools.load_release(args)
                release_tools.check_archive(release, reports)
                _, verification = release_tools.verified_export(release, reports, metadata)
                output["verified_ipa_sha256"] = verification["ipa_sha256"]
                output["uploaded"] = False
            else:
                _, reports, _ = release_tools.load_release(args)
                state = json.loads((reports / "api-upload-progress.json").read_text())
                require(state["app_id"] == args.app_id, "Saved upload belongs to a different app.")
                build_id = resource_id(state["build_upload_id"])
                remote = client.request("GET", "/v1/buildUploads/" + build_id)["data"]
                output.update(build_upload_id=build_id, apple_state=remote["attributes"].get("state", {}))
            print(json.dumps(safe_report(output), indent=2))
        return 0
    except (Error, OSError, ValueError, KeyError, TypeError) as error:
        # Avoid urllib exceptions that could include a signed URL in their text.
        message = safe_text(error) if isinstance(error, Error) else type(error).__name__ + ": operation stopped; details omitted"
        print("API upload stopped: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
