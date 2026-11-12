#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
episode_dir="$(cd -- "${script_dir}/.." && pwd)"
output_dir="${episode_dir}/public/audio"
raw_path="$(mktemp --suffix=.fplagent-knockout-score.wav)"
output_path="${output_dir}/fplagent-knockout-score.wav"
trap 'rm -f -- "${raw_path}"' EXIT

mkdir -p "${output_dir}"

cd "${episode_dir}"
node scripts/build-knockout-score.mjs "${raw_path}"

ffmpeg -hide_banner -loglevel error -y \
  -i "${raw_path}" \
  -af "highpass=f=30,lowpass=f=14500,acompressor=threshold=0.24:ratio=2.1:attack=14:release=160:makeup=1.18,loudnorm=I=-18:LRA=8:TP=-2.2" \
  -ar 48000 -c:a pcm_s16le "${output_path}"

echo "Built ${output_path}"
