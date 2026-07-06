"""Read/write ~/.aws/credentials and validate via STS."""

from __future__ import annotations

import configparser
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

CREDENTIALS_PATH = Path.home() / ".aws" / "credentials"
CONFIG_PATH = Path.home() / ".aws" / "config"
DEFAULT_PROFILE = "default"


def _read_ini(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    if path.exists():
        cp.read(path)
    return cp


def read_credentials(profile: str = DEFAULT_PROFILE) -> dict:
    cp = _read_ini(CREDENTIALS_PATH)
    if not cp.has_section(profile):
        return {}
    section = cp[profile]
    key_id = section.get("aws_access_key_id", "").strip()
    if not key_id:
        return {}
    return {
        "profile": profile,
        "aws_access_key_id": key_id,
        "aws_secret_access_key": section.get("aws_secret_access_key", "").strip(),
        "aws_session_token": section.get("aws_session_token", "").strip() or None,
    }


def read_region(profile: str = DEFAULT_PROFILE) -> str | None:
    cp = _read_ini(CONFIG_PATH)
    section = f"profile {profile}" if profile != DEFAULT_PROFILE else DEFAULT_PROFILE
    if cp.has_section(section):
        region = cp.get(section, "region", fallback="").strip()
        if region:
            return region
    return None


def write_credentials(
    *,
    access_key_id: str,
    secret_access_key: str,
    session_token: str | None = None,
    profile: str = DEFAULT_PROFILE,
) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    cp = _read_ini(CREDENTIALS_PATH)
    if not cp.has_section(profile):
        cp.add_section(profile)
    cp[profile]["aws_access_key_id"] = access_key_id.strip()
    cp[profile]["aws_secret_access_key"] = secret_access_key.strip()
    if session_token and session_token.strip():
        cp[profile]["aws_session_token"] = session_token.strip()
    elif cp.has_option(profile, "aws_session_token"):
        cp.remove_option(profile, "aws_session_token")
    with CREDENTIALS_PATH.open("w", encoding="utf-8") as fh:
        cp.write(fh)


def write_region(region: str, profile: str = DEFAULT_PROFILE) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cp = _read_ini(CONFIG_PATH)
    section = f"profile {profile}" if profile != DEFAULT_PROFILE else DEFAULT_PROFILE
    if not cp.has_section(section):
        cp.add_section(section)
    cp[section]["region"] = region.strip()
    with CONFIG_PATH.open("w", encoding="utf-8") as fh:
        cp.write(fh)


def mask_secret(value: str | None, visible: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]


def credentials_status(profile: str = DEFAULT_PROFILE, region: str = "us-east-1") -> dict:
    creds = read_credentials(profile)
    reg = read_region(profile) or region
    out = {
        "profile": profile,
        "credentials_path": str(CREDENTIALS_PATH),
        "config_path": str(CONFIG_PATH),
        "region": reg,
        "has_credentials": bool(creds.get("aws_access_key_id")),
        "access_key_id": creds.get("aws_access_key_id", ""),
        "access_key_masked": mask_secret(creds.get("aws_access_key_id"), 4),
        "secret_configured": bool(creds.get("aws_secret_access_key")),
        "secret_masked": mask_secret(creds.get("aws_secret_access_key"), 4),
        "has_session_token": bool(creds.get("aws_session_token")),
        "session_token_masked": mask_secret(creds.get("aws_session_token"), 6),
        "valid": False,
        "account": None,
        "arn": None,
        "user_id": None,
        "error": None,
    }
    if not out["has_credentials"]:
        out["error"] = "no_credentials"
        return out
    try:
        session = boto3.session.Session(region_name=reg, **{
            k: v for k, v in creds.items()
            if k.startswith("aws_") and v
        })
        sts = session.client("sts")
        ident = sts.get_caller_identity()
        out["valid"] = True
        out["account"] = ident.get("Account")
        out["arn"] = ident.get("Arn")
        out["user_id"] = ident.get("UserId")
    except NoCredentialsError:
        out["error"] = "no_credentials"
    except ClientError as e:
        out["error"] = e.response.get("Error", {}).get("Message", str(e))
    except BotoCoreError as e:
        out["error"] = str(e)
    return out


def test_credentials_payload(
    *,
    access_key_id: str,
    secret_access_key: str,
    session_token: str | None = None,
    region: str = "us-east-1",
) -> dict:
    try:
        session = boto3.session.Session(
            region_name=region,
            aws_access_key_id=access_key_id.strip(),
            aws_secret_access_key=secret_access_key.strip(),
            aws_session_token=session_token.strip() if session_token else None,
        )
        ident = session.client("sts").get_caller_identity()
        return {
            "valid": True,
            "account": ident.get("Account"),
            "arn": ident.get("Arn"),
            "user_id": ident.get("UserId"),
        }
    except (ClientError, BotoCoreError, NoCredentialsError) as e:
        msg = str(e)
        if isinstance(e, ClientError):
            msg = e.response.get("Error", {}).get("Message", msg)
        return {"valid": False, "error": msg}
