"""Publish the local partitioned parquet tree to HuggingFace + Cloudflare R2.

R2 is the BI query backend; HF is the public distribution copy + demo source.
Both receive the same tree. Credentials come from env vars:

    HF_TOKEN, HF_REPO                 (e.g. "some-org/usaspending-bulk")
    R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET

HF upload batches files into commits (HF rate-limits ~128 commits/hr), modeled on
opm/opm_pipeline/uploader.py. R2 upload reuses the boto3 pattern from
pull_usaspending / usajobs_historical/web/api/data_loader.py.

Heavy deps (huggingface_hub, boto3) are imported lazily so this module loads in
environments that only need the manifest/dataclass logic.
"""
from __future__ import annotations

import os
import time
from pathlib import Path


def iter_tree(root: Path) -> list[tuple[Path, str]]:
    """(local_path, key) for every parquet under root, key relative to root with / separators."""
    return [(p, str(p.relative_to(root).as_posix())) for p in sorted(root.rglob("*.parquet"))]


def publish_to_hf(files: list[tuple[Path, str]], repo_id: str, token: str | None = None,
                  batch_size: int = 40, max_retries: int = 3) -> None:
    """Upload (local, key) pairs to a HF dataset repo in batched commits."""
    from huggingface_hub import CommitOperationAdd, HfApi

    token = token or os.environ["HF_TOKEN"]
    api = HfApi(token=token)
    api.create_repo(repo_id, repo_type="dataset", exist_ok=True)

    for i in range(0, len(files), batch_size):
        batch = files[i:i + batch_size]
        ops = [CommitOperationAdd(path_in_repo=key, path_or_fileobj=str(local))
               for local, key in batch]
        for attempt in range(max_retries):
            try:
                api.create_commit(
                    repo_id, operations=ops, repo_type="dataset",
                    commit_message=f"Add {len(ops)} parquet files (batch {i // batch_size + 1})",
                )
                break
            except Exception:
                if attempt == max_retries - 1:
                    raise
                time.sleep(min(10 * 2 ** attempt, 120))


def r2_client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )


def publish_to_r2(files: list[tuple[Path, str]], bucket: str | None = None) -> None:
    """Upload (local, key) pairs to the R2 bucket."""
    bucket = bucket or os.environ["R2_BUCKET"]
    client = r2_client()
    for local, key in files:
        client.upload_file(str(local), bucket, key)
