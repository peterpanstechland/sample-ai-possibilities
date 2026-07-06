"""Shared boto3 clients — credentials from ~/.aws/credentials, optional US proxy for Bedrock."""

from __future__ import annotations

import os

import boto3
from botocore.config import Config

# Domains to add to VPN「强制走美国节点」规则（Claude / Anthropic on Bedrock）
BEDROCK_US_PROXY_DOMAINS = (
    "bedrock-runtime.us-east-1.amazonaws.com",
    "bedrock.us-east-1.amazonaws.com",
    "bedrock-runtime.us-west-2.amazonaws.com",
    "bedrock.us-west-2.amazonaws.com",
)


def credentials_from_file() -> dict:
    from aws_credentials import read_credentials
    creds = read_credentials()
    if not creds:
        return {}
    return {
        "aws_access_key_id": creds["aws_access_key_id"],
        "aws_secret_access_key": creds.get("aws_secret_access_key"),
        "aws_session_token": creds.get("aws_session_token"),
    }


def proxy_url() -> str | None:
    """HTTPS proxy for Bedrock (Claude geo). Set OBSERVE_HTTPS_PROXY or HTTPS_PROXY."""
    for key in ("OBSERVE_HTTPS_PROXY", "HTTPS_PROXY", "https_proxy", "ALL_PROXY"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return None


def needs_us_proxy(model_id: str | None) -> bool:
    return bool(model_id and "anthropic" in model_id.lower())


def boto_config(use_proxy: bool) -> Config | None:
    if not use_proxy:
        return None
    url = proxy_url()
    if not url:
        return None
    return Config(proxies={"http": url, "https": url})


def aws_client(service: str, region: str = "us-east-1", *, use_proxy: bool = False):
    creds = credentials_from_file()
    cfg = boto_config(use_proxy)
    session = boto3.session.Session(region_name=region, **creds)
    if cfg:
        return session.client(service, config=cfg)
    return session.client(service)
