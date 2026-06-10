#!/usr/bin/env bash
# Source this file before running BEHAVIOR / OmniGibson real-data scripts.
#
# Usage:
#   source real_data_pipeline/env_behavior.sh
#   python real_data_pipeline/stages/runtime_probe.py

set -e

BEHAVIOR_ROOT="${BEHAVIOR_ROOT:-/root/autodl-tmp/BEHAVIOR-1K}"
CONDA_ROOT="${CONDA_ROOT:-/root/miniconda3}"
CONDA_ENV_PATH="${CONDA_ENV_PATH:-/root/autodl-tmp/conda/envs/behavior-cu128}"

if [ ! -f "${CONDA_ROOT}/etc/profile.d/conda.sh" ]; then
  echo "Cannot find conda.sh under ${CONDA_ROOT}" >&2
  return 1 2>/dev/null || exit 1
fi

if [ ! -x "${CONDA_ENV_PATH}/bin/python" ]; then
  echo "Cannot find behavior env python under ${CONDA_ENV_PATH}" >&2
  return 1 2>/dev/null || exit 1
fi

source "${CONDA_ROOT}/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV_PATH}"

export BEHAVIOR_ROOT
export OMNIGIBSON_DATA_PATH="${OMNIGIBSON_DATA_PATH:-${BEHAVIOR_ROOT}/datasets}"
export OMNIGIBSON_HEADLESS="${OMNIGIBSON_HEADLESS:-True}"
export OMNI_KIT_ACCEPT_EULA="${OMNI_KIT_ACCEPT_EULA:-YES}"

# AutoDL headless Vulkan guidance: use libEGL_nvidia, not the host-mounted
# libGLX_nvidia ICD.  The host nvidia_icd.json can be read-only, so force the
# project-local AutoDL-compatible ICD whenever it exists.
if [ -f /etc/vulkan/icd.d/my_nvidia_icd.json ]; then
  export VK_ICD_FILENAMES="/etc/vulkan/icd.d/my_nvidia_icd.json"
elif [ -n "${VK_ICD_FILENAMES:-}" ] && [ ! -f "${VK_ICD_FILENAMES}" ]; then
  echo "VK_ICD_FILENAMES=${VK_ICD_FILENAMES} does not exist; auto-detecting Vulkan ICD." >&2
  unset VK_ICD_FILENAMES
elif [ -z "${VK_ICD_FILENAMES:-}" ] && [ -f /etc/vulkan/icd.d/nvidia_icd.json ]; then
  export VK_ICD_FILENAMES="/etc/vulkan/icd.d/nvidia_icd.json"
fi
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-root}"
mkdir -p "${XDG_RUNTIME_DIR}"
chmod 700 "${XDG_RUNTIME_DIR}" 2>/dev/null || true

ISAACSIM_SITE="${CONDA_ENV_PATH}/lib/python3.10/site-packages/isaacsim"
ISAACSIM_LD_PATHS=(
  "${CONDA_ENV_PATH}/lib/python3.10/site-packages/omni"
  "${ISAACSIM_SITE}/extscache/omni.usd.libs-1.0.1+d02c707b.lx64.r.cp310/bin"
  "${ISAACSIM_SITE}/extscache/omni.hydra.rtx-1.0.0+d02c707b.lx64.r/bin"
  "${ISAACSIM_SITE}/extscache/omni.hydra.rtx-1.0.0+d02c707b.lx64.r/bin/deps"
  "${ISAACSIM_SITE}/extsPhysics/omni.physx/bin"
  "${ISAACSIM_SITE}/extsPhysics/omni.convexdecomposition/bin"
  "${ISAACSIM_SITE}/extsPhysics/omni.physx.cooking/bin"
)
for isaac_path in "${ISAACSIM_LD_PATHS[@]}"; do
  if [ -d "${isaac_path}" ]; then
    case ":${LD_LIBRARY_PATH:-}:" in
      *":${isaac_path}:"*) ;;
      *) export LD_LIBRARY_PATH="${isaac_path}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" ;;
    esac
  fi
done

echo "Activated behavior env: $(which python)"
echo "OMNIGIBSON_DATA_PATH=${OMNIGIBSON_DATA_PATH}"
echo "OMNI_KIT_ACCEPT_EULA=${OMNI_KIT_ACCEPT_EULA}"
echo "VK_ICD_FILENAMES=${VK_ICD_FILENAMES}"
echo "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}"
