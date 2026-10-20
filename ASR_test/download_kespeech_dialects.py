from collections import defaultdict
from io import BytesIO
from pathlib import Path
import csv
import os
import time
import wave

from huggingface_hub import hf_hub_download
from huggingface_hub.utils import close_session
import pyarrow.parquet as pq


DATASET_ID = "TwinkStart/KeSpeech"
SPLIT = "test"
SHARD_COUNT = 8

TARGET_DIALECTS = {
    "Northeastern": "dongbei",
    "Zhongyuan": "henan",
    "Ji-Lu": "shandong",
    "Jiao-Liao": "shandong",
}

REGION_NAMES = {
    "dongbei": "东北",
    "henan": "河南",
    "shandong": "山东",
}

proxy_url = os.getenv("HF_PROXY", "http://127.0.0.1:10809")
download_max_attempts = int(os.getenv("HF_DOWNLOAD_MAX_ATTEMPTS", "20"))

if proxy_url:
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ.pop("ALL_PROXY", None)
    os.environ.pop("all_proxy", None)
    print(f"using proxy: {proxy_url}")

out_root = Path("downloaded_audio") / "kespeech"
out_root.mkdir(parents=True, exist_ok=True)
metadata_path = out_root / "metadata.csv"


def wav_duration(audio_bytes):
    try:
        with wave.open(BytesIO(audio_bytes), "rb") as wav_file:
            return wav_file.getnframes() / wav_file.getframerate()
    except wave.Error:
        return None


def download_with_retry(filename):
    last_error = None
    for attempt in range(1, download_max_attempts + 1):
        try:
            return hf_hub_download(
                repo_id=DATASET_ID,
                repo_type="dataset",
                filename=filename,
            )
        except Exception as exc:
            last_error = exc
            close_session()
            wait_seconds = min(60, attempt * 5)
            print(
                f"download failed ({attempt}/{download_max_attempts}): {filename}\n"
                f"{type(exc).__name__}: {exc}\n"
                f"retrying in {wait_seconds}s..."
            )
            time.sleep(wait_seconds)

    raise RuntimeError(f"failed to download after {download_max_attempts} attempts: {filename}") from last_error


def make_row(row, region, region_index, global_index):
    audio = row["audio"] or {}
    audio_bytes = audio.get("bytes")
    source_audio_path = row.get("WavPath") or audio.get("path") or ""
    suffix = Path(source_audio_path).suffix or ".wav"
    dst = out_root / region / f"{region_index:08d}{suffix}"
    saved_path = dst.relative_to(out_root).as_posix()
    duration = wav_duration(audio_bytes) if audio_bytes else None

    skipped_reason = ""
    if not audio_bytes:
        skipped_reason = "missing_audio_bytes"
    elif dst.exists():
        skipped_reason = "already_exists"
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(audio_bytes)

    return {
        "saved_path": saved_path if skipped_reason != "missing_audio_bytes" else "",
        "region": region,
        "region_name": REGION_NAMES[region],
        "dialect": row.get("Dialect", ""),
        "duration_seconds": "" if duration is None else round(duration, 3),
        "text": row.get("Text", ""),
        "id": row.get("ID", ""),
        "source_wav_path": source_audio_path,
        "global_index": global_index,
        "region_index": region_index,
        "skipped_reason": skipped_reason,
    }


fieldnames = [
    "saved_path",
    "region",
    "region_name",
    "dialect",
    "duration_seconds",
    "text",
    "id",
    "source_wav_path",
    "global_index",
    "region_index",
    "skipped_reason",
]

processed = 0
saved = 0
skipped = 0
region_counts = defaultdict(int)
rows_by_region = defaultdict(list)

with metadata_path.open("w", encoding="utf-8-sig", newline="") as metadata_file:
    writer = csv.DictWriter(metadata_file, fieldnames=fieldnames)
    writer.writeheader()

    for shard_index in range(SHARD_COUNT):
        filename = f"data/{SPLIT}-{shard_index:05d}-of-{SHARD_COUNT:05d}.parquet"
        print(f"downloading/using shard: {filename}")
        parquet_path = download_with_retry(filename)
        parquet_file = pq.ParquetFile(parquet_path)

        for row_group_index in range(parquet_file.num_row_groups):
            table = parquet_file.read_row_group(row_group_index)
            for row in table.to_pylist():
                dialect = row.get("Dialect")
                region = TARGET_DIALECTS.get(dialect)
                if region is None:
                    continue

                exported = make_row(
                    row=row,
                    region=region,
                    region_index=region_counts[region],
                    global_index=processed,
                )
                writer.writerow(exported)
                rows_by_region[region].append(exported)

                saved += int(exported["skipped_reason"] in ("", "already_exists"))
                skipped += int(bool(exported["skipped_reason"]))
                processed += 1
                region_counts[region] += 1

                if processed % 100 == 0:
                    print(f"processed {processed}, saved {saved}, skipped {skipped}")
                    metadata_file.flush()

for region, rows in rows_by_region.items():
    region_metadata_path = out_root / region / "metadata.csv"
    with region_metadata_path.open("w", encoding="utf-8-sig", newline="") as region_file:
        writer = csv.DictWriter(region_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

print(f"done: processed {processed}, saved {saved}, skipped {skipped}")
for region in sorted(REGION_NAMES):
    print(f"{REGION_NAMES[region]} ({region}): {region_counts[region]}")
print(f"audio dir: {out_root.resolve()}")
print(f"metadata: {metadata_path.resolve()}")
