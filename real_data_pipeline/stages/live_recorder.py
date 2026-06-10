#!/usr/bin/env python3
"""EviStateBench 真实 benchmark 第 3 步：OmniGibson 仿真真值记录器。

完整 stage 设计写在 ``real_data_pipeline/README.md``。这里保留短版契约：

1. 本脚本属于 benchmark generator，不属于 EviStateDB baseline engine。
2. 本脚本负责从真实 OmniGibson episode 记录 simulator truth。
3. 本脚本不负责自己求解 BEHAVIOR 任务；任务进展来自外部 action source。
4. 最终第 3 步应产出 hidden truth timeline 和 clean StateObservation stream。
5. smoke/probe 模式可以保留，但不能替代最终真实 benchmark generator。

当前可执行契约：

- 输入：BEHAVIOR task instance（activity / scene / definition id / instance id）
  和明确 action source（noop / random / jsonl action vector / primitive_jsonl）。
- 运行：启动 OmniGibson live simulator，reset 后按 action source step。
- 输出：episode_manifest.json、simulator_truth_snapshots.jsonl、
  hidden_state_timeline.jsonl、clean_state_observations.jsonl、task_spec.json、
  generation_report.{json,md}。
- 边界：jsonl action source 是低层 action vector replay；primitive_jsonl 是显式
  semantic primitive script replay。recorder 不在内部临时“解任务”。
"""

from __future__ import annotations

import argparse
import faulthandler
import json
import os
import subprocess
import sys
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evistatebench.schema import StateObservation


DEFAULT_BEHAVIOR_ROOT = Path("/root/autodl-tmp/BEHAVIOR-1K")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "real_data_pipeline" / "artifacts" / "runtime_probe"
ARTIFACT_VERSION = "real_og_stage3_v0"

STATE_NAME_TO_PREDICATE = {
    "AttachedTo": "attached",
    "Broken": "broken",
    "Burnt": "burnt",
    "ContainedParticles": "contained_particles",
    "Contains": "contains",
    "ContactParticles": "contact_particles",
    "Cooked": "cooked",
    "Covered": "covered",
    "Draped": "draped",
    "Filled": "filled",
    "Folded": "folded",
    "Frozen": "frozen",
    "Heated": "hot",
    "Inside": "inside",
    "Joint": "joint_state",
    "MaxTemperature": "max_temperature",
    "ModifiedParticles": "modified_particles",
    "NextTo": "nextto",
    "OnFire": "on_fire",
    "OnTop": "ontop",
    "Open": "open",
    "Overlaid": "overlaid",
    "Saturated": "saturated",
    "SlicerActive": "slicer_active",
    "Temperature": "temperature",
    "ToggledOn": "toggled_on",
    "Touching": "touching",
    "Under": "under",
    "Unfolded": "unfolded",
}

OBJECT_RELATION_STATE_NAMES = frozenset(
    {"AttachedTo", "Draped", "Inside", "NextTo", "OnTop", "Overlaid", "Touching", "Under"}
)
SYSTEM_RELATION_STATE_NAMES = frozenset(
    {"ContainedParticles", "Contains", "ContactParticles", "Covered", "Filled", "ModifiedParticles", "Saturated"}
)
DIAGNOSTIC_STATE_NAMES = frozenset(
    {"AABB", "ContactBodies", "HeatSourceOrSink", "HorizontalAdjacency", "Pose", "VerticalAdjacency"}
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def to_jsonable(value: Any) -> Any:
    """Convert simulator / tensor / numpy values into JSON-compatible values."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "detach") and callable(value.detach):
        return to_jsonable(value.detach().cpu().tolist())
    if hasattr(value, "cpu") and callable(value.cpu):
        try:
            return to_jsonable(value.cpu().tolist())
        except Exception:
            pass
    if hasattr(value, "tolist") and callable(value.tolist):
        try:
            return to_jsonable(value.tolist())
        except Exception:
            pass
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return repr(value)


def make_episode_id(args: argparse.Namespace) -> str:
    if args.episode_id:
        return args.episode_id
    return (
        f"og_truth__{args.activity_name}__"
        f"{args.activity_definition_id}_{args.activity_instance_id}__"
        f"{args.action_source}_{args.steps}"
    )


def safe_path_component(value: str) -> str:
    safe_chars: list[str] = []
    for char in value:
        if char.isalnum() or char in {"-", "_", "."}:
            safe_chars.append(char)
        else:
            safe_chars.append("_")
    return "".join(safe_chars).strip("_") or "episode"


def episode_output_dir(args: argparse.Namespace) -> Path:
    if args.episode_output_dir is not None:
        return args.episode_output_dir
    return args.output_dir / "episodes" / safe_path_component(make_episode_id(args))


def action_jsonl_path(args: argparse.Namespace) -> Path | None:
    return args.action_jsonl.resolve() if args.action_jsonl is not None else None


def state_predicate_name(state_name: str) -> str:
    if state_name in STATE_NAME_TO_PREDICATE:
        return STATE_NAME_TO_PREDICATE[state_name]

    chars: list[str] = []
    for index, char in enumerate(state_name):
        if char.isupper() and index > 0:
            chars.append("_")
        chars.append(char.lower())
    return "".join(chars)


def observation_kind(predicate_name: str, value: Any) -> str:
    if predicate_name in {"object_pose", "object_velocity", "joint_state", "robot_pose"}:
        return predicate_name
    if isinstance(value, bool):
        return "predicate_state"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "numeric_state"
    if predicate_name in {"temperature", "max_temperature"}:
        return "numeric_state"
    return "simulator_diagnostic"


def object_name(obj: Any) -> str:
    try:
        name = getattr(obj, "name", None)
    except Exception:
        name = None
    return str(name) if name else repr(obj)


def entity_record_id(entity: Any, reverse_scope: dict[int, str]) -> str:
    return reverse_scope.get(id(entity), object_name(entity))


def entity_states(entity: Any) -> tuple[dict[Any, Any], str | None]:
    try:
        return getattr(entity, "states", {}) or {}, None
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"


def set_runtime_seed(seed: int | None) -> None:
    if seed is None:
        return
    import random

    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except Exception:
        pass
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except Exception:
        pass


def object_scope_items(env: Any, object_limit: int | None) -> list[tuple[str, Any]]:
    scope = getattr(env.task, "object_scope", {}) or {}
    items = list(scope.items())
    if object_limit is not None:
        items = items[:object_limit]
    return items


def reverse_scope_map(scope_items: list[tuple[str, Any]]) -> dict[int, str]:
    return {id(entity): str(name) for name, entity in scope_items}


def load_action_jsonl(path: Path) -> list[Any]:
    actions: list[Any] = []
    for line_index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict) and "action" in row:
            actions.append(row["action"])
        elif isinstance(row, dict) and "value" in row:
            actions.append(row["value"])
        else:
            actions.append(row)
    return actions


def load_primitive_jsonl(path: Path) -> list[dict[str, Any]]:
    primitives: list[dict[str, Any]] = []
    for line_index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        row = json.loads(line)
        if isinstance(row, str):
            row = {"primitive": row}
        if not isinstance(row, dict):
            raise ValueError(f"Primitive JSONL line {line_index} must be an object or string")
        if "primitive" not in row and "name" in row:
            row["primitive"] = row["name"]
        if "primitive" not in row and "op" in row:
            row["primitive"] = row["op"]
        if "primitive" not in row:
            raise ValueError(f"Primitive JSONL line {line_index} is missing 'primitive'")
        primitives.append({"line_index": line_index, **row})
    return primitives


def action_summary(action: Any, source: str, step_index: int) -> dict[str, Any]:
    value = to_jsonable(action)
    length = len(value) if isinstance(value, list) else None
    return {
        "source": source,
        "step_index": step_index,
        "value": value,
        "value_length": length,
    }


def call_method(obj: Any, method_name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    method = getattr(obj, method_name, None)
    if not callable(method):
        return {"ok": False, "error": f"missing method {method_name}"}
    try:
        return {"ok": True, "value": to_jsonable(method(*args, **kwargs))}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def compact_error(exc: BaseException) -> dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback_tail": traceback.format_exc().splitlines()[-40:],
    }


def task_scene_instance(args: argparse.Namespace) -> str:
    return (
        f"{args.scene_model}_task_{args.activity_name}_"
        f"{args.activity_definition_id}_{args.activity_instance_id}_template"
    )


def expected_task_template_path(args: argparse.Namespace) -> Path:
    return (
        args.behavior_root
        / "datasets"
        / "2025-challenge-task-instances"
        / "scenes"
        / args.scene_model
        / "json"
        / f"{task_scene_instance(args)}.json"
    )


def summarize_task_template(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}

    data = read_json(path)
    task_meta = data.get("metadata", {}).get("task", {})
    scene_args = data.get("init_info", {}).get("args", {})
    inst_to_name = task_meta.get("inst_to_name", {})
    robot_poses = task_meta.get("robot_poses", {})
    stale_scene_file = scene_args.get("scene_file")

    return {
        "path": str(path),
        "exists": True,
        "top_level_keys": sorted(data.keys()),
        "scene_model": scene_args.get("scene_model"),
        "scene_instance": scene_args.get("scene_instance"),
        "scene_file": stale_scene_file,
        "scene_file_exists": bool(stale_scene_file and Path(stale_scene_file).exists()),
        "object_scope_count": len(inst_to_name) if isinstance(inst_to_name, dict) else 0,
        "object_scope_sample": list(inst_to_name.items())[:8] if isinstance(inst_to_name, dict) else [],
        "robot_pose_types": sorted(robot_poses.keys()) if isinstance(robot_poses, dict) else [],
        "note": (
            "The runtime config uses scene_model + scene_instance resolution. "
            "It does not trust the absolute scene_file embedded in the template."
        ),
    }


def probe_vulkan_summary() -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["vulkaninfo", "--summary"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    lines = text.splitlines()
    device_names = [
        line.split("=", 1)[1].strip()
        for line in lines
        if line.strip().startswith("deviceName") and "=" in line
    ]
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "device_names": device_names,
        "has_nvidia_device": any("nvidia" in name.lower() or "geforce" in name.lower() for name in device_names),
        "has_llvmpipe": any("llvmpipe" in name.lower() for name in device_names),
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }


def configure_behavior_paths(behavior_root: Path) -> dict[str, str]:
    og_root = behavior_root / "OmniGibson"
    bddl_root = behavior_root / "bddl3"
    datasets_root = behavior_root / "datasets"
    conda_env = Path(sys.executable).resolve().parents[1]
    isaacsim_site = conda_env / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages" / "isaacsim"
    omni_site = conda_env / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages" / "omni"

    for path in (og_root, bddl_root):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)

    os.environ.setdefault("BEHAVIOR_ROOT", str(behavior_root))
    os.environ.setdefault("OMNIGIBSON_DATA_PATH", str(datasets_root))
    os.environ.setdefault("OMNIGIBSON_HEADLESS", "True")
    os.environ.setdefault("OMNI_KIT_ACCEPT_EULA", "YES")

    ld_paths = [
        omni_site,
        isaacsim_site / "extscache" / "omni.usd.libs-1.0.1+d02c707b.lx64.r.cp310" / "bin",
        isaacsim_site / "extscache" / "omni.hydra.rtx-1.0.0+d02c707b.lx64.r" / "bin",
        isaacsim_site / "extscache" / "omni.hydra.rtx-1.0.0+d02c707b.lx64.r" / "bin" / "deps",
        isaacsim_site / "extsPhysics" / "omni.physx" / "bin",
        isaacsim_site / "extsPhysics" / "omni.convexdecomposition" / "bin",
        isaacsim_site / "extsPhysics" / "omni.physx.cooking" / "bin",
    ]
    existing_ld = os.environ.get("LD_LIBRARY_PATH", "")
    existing_parts = [part for part in existing_ld.split(os.pathsep) if part]
    for path in reversed([str(path) for path in ld_paths if path.exists()]):
        if path not in existing_parts:
            existing_parts.insert(0, path)
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(existing_parts)

    return {
        "BEHAVIOR_ROOT": os.environ["BEHAVIOR_ROOT"],
        "OMNIGIBSON_DATA_PATH": os.environ["OMNIGIBSON_DATA_PATH"],
        "OMNIGIBSON_HEADLESS": os.environ["OMNIGIBSON_HEADLESS"],
        "OMNI_KIT_ACCEPT_EULA": os.environ["OMNI_KIT_ACCEPT_EULA"],
        "LD_LIBRARY_PATH_PREFIX": os.pathsep.join(str(path) for path in ld_paths if path.exists()),
        "PYTHONPATH_PREFIX": os.pathsep.join([str(og_root), str(bddl_root)]),
    }


def build_robot_config(args: argparse.Namespace) -> dict[str, Any]:
    default_config = {
        "type": args.robot_type,
        "obs_modalities": [],
    }
    if args.action_source != "primitive_jsonl" or not args.use_primitive_robot_config:
        return default_config

    config_path = (
        args.behavior_root
        / "OmniGibson"
        / "omnigibson"
        / "configs"
        / f"{args.robot_type.lower()}_primitives.yaml"
    )
    if not config_path.exists():
        return default_config

    try:
        import yaml

        full_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        robots = full_config.get("robots") or []
        if not robots:
            return default_config
        robot_config = dict(robots[0])
        robot_config["obs_modalities"] = []
        robot_config["disable_grasp_handling"] = True
        return robot_config
    except Exception as exc:
        raise RuntimeError(f"Failed to load primitive robot config {config_path}: {exc}") from exc


def build_env_config(args: argparse.Namespace) -> dict[str, Any]:
    termination_max_steps = max(args.steps + 5, args.max_runtime_steps + 5 if args.max_runtime_steps > 0 else 10)
    return {
        "env": {
            "automatic_reset": False,
            "flatten_action_space": False,
            "flatten_obs_space": False,
            "external_sensors": None,
            "device": None if args.device == "none" else args.device,
        },
        "render": {
            "viewer_width": args.viewer_width,
            "viewer_height": args.viewer_height,
        },
        "scene": {
            "type": "InteractiveTraversableScene",
            "scene_model": args.scene_model,
            "scene_instance": task_scene_instance(args),
            "trav_map_resolution": 0.1,
            "default_erosion_radius": 0.0,
            "trav_map_with_objects": True,
            "num_waypoints": 1,
            "waypoint_resolution": 0.2,
            "seg_map_resolution": args.seg_map_resolution if args.enable_seg_map else None,
            "load_task_relevant_only": not args.full_scene,
            "load_structure_categories": args.load_structure_categories or args.full_scene,
            "include_robots": True,
        },
        "robots": [build_robot_config(args)],
        "objects": [],
        "task": {
            "type": "BehaviorTask",
            "activity_name": args.activity_name,
            "activity_definition_id": args.activity_definition_id,
            "activity_instance_id": args.activity_instance_id,
            "online_object_sampling": False,
            "use_presampled_robot_pose": args.use_presampled_robot_pose,
            "randomize_presampled_pose": False,
            "highlight_task_relevant_objects": False,
            "termination_config": {"max_steps": termination_max_steps},
            "reward_config": {"r_potential": 1.0},
            "include_obs": False,
        },
    }


def make_zero_action(robot: Any) -> Any:
    """Return a stable no-op-like action for one robot."""
    try:
        import numpy as np

        space = robot.action_space
        if hasattr(space, "shape") and space.shape is not None:
            dtype = getattr(space, "dtype", None) or np.float32
            return np.zeros(space.shape, dtype=dtype)
    except Exception:
        pass

    action = robot.action_space.sample()
    try:
        return action * 0
    except Exception:
        return action


def coerce_action_for_robot(robot: Any, action: Any) -> Any:
    """Convert JSON-compatible action vectors back to the robot action dtype."""
    if isinstance(action, dict):
        return action

    try:
        import numpy as np

        space = robot.action_space
        expected_shape = getattr(space, "shape", None)
        dtype = getattr(space, "dtype", None) or np.float32
        array = np.asarray(action, dtype=dtype)
        if expected_shape is not None and tuple(array.shape) != tuple(expected_shape):
            raise ValueError(f"action shape {tuple(array.shape)} does not match robot action space {expected_shape}")
        return array
    except ValueError:
        raise
    except Exception:
        return action


PRIMITIVE_ALIASES = {
    "ATTACH_TO": "ATTACH",
    "PICK": "GRASP",
    "PICK_UP": "GRASP",
    "PUT_ON": "PLACE_ON_TOP",
    "PLACE_ON": "PLACE_ON_TOP",
    "PUT_INSIDE": "PLACE_INSIDE",
    "TURN_ON": "TOGGLE_ON",
    "TURN_OFF": "TOGGLE_OFF",
    "NO_OP": "WAIT",
    "NOOP": "WAIT",
    "STATE_SET": "SET_STATE",
    "SET_UNARY_STATE": "SET_STATE",
    "RELATION_SET": "SET_RELATION",
    "SET_OBJECT_RELATION": "SET_RELATION",
}

LOCAL_PRIMITIVES = frozenset({"ATTACH", "SET_RELATION", "SET_STATE", "WAIT"})


def normalize_primitive_name(name: Any) -> str:
    text = str(name).strip().upper().replace("-", "_").replace(" ", "_")
    return PRIMITIVE_ALIASES.get(text, text)


def primitive_argument_refs(row: dict[str, Any]) -> list[Any]:
    if "args" in row:
        args = row["args"]
        return list(args) if isinstance(args, list) else [args]
    if "objects" in row:
        objects = row["objects"]
        return list(objects) if isinstance(objects, list) else [objects]
    if "child" in row and "parent" in row:
        return [row["child"], row["parent"]]
    if "object" in row and "parent" in row:
        return [row["object"], row["parent"]]
    if "object" in row and "target" in row:
        return [row["object"], row["target"]]
    if "object" in row:
        return [row["object"]]
    if "target" in row:
        return [row["target"]]
    return []


def bool_option(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return bool(value)


def primitive_value(row: dict[str, Any], default: Any = True) -> Any:
    for key in ("value", "observed_value", "state_value", "to"):
        if key in row:
            return row[key]
    return default


def primitive_set_kwargs(row: dict[str, Any], allowed_keys: set[str]) -> dict[str, Any]:
    kwargs = row.get("set_kwargs")
    if kwargs is not None:
        if not isinstance(kwargs, dict):
            raise ValueError(f"set_kwargs must be an object, got {type(kwargs).__name__}")
        return dict(kwargs)
    return {key: row[key] for key in allowed_keys if key in row}


def find_state_by_predicate(entity: Any, predicate_name: str) -> tuple[str | None, Any | None, str | None]:
    states, states_error = entity_states(entity)
    if states_error:
        return None, None, states_error
    normalized_predicate = str(predicate_name).strip()
    for state_key, state in states.items():
        state_name = state_class_name(state_key, state)
        if state_name == normalized_predicate or state_predicate_name(state_name) == normalized_predicate:
            return state_name, state, None
    return None, None, f"missing state for predicate {predicate_name!r}"


def normalize_registry_result(result: Any, *, ref: Any, index: int | None = None) -> Any:
    if result is None:
        return None
    if isinstance(result, (set, list, tuple)):
        items = sorted(result, key=object_name)
        if not items:
            return None
        if index is not None:
            if index < 0 or index >= len(items):
                raise ValueError(f"Object reference {ref!r} index {index} is out of range for {len(items)} matches")
            return items[index]
        if len(items) == 1:
            return items[0]
        names = [object_name(item) for item in items[:10]]
        raise ValueError(f"Object reference {ref!r} is ambiguous; first matches: {names}")
    return result


def resolve_scene_registry_object(env: Any, key: str, value: Any, *, ref: Any, index: int | None = None) -> Any:
    registry = getattr(getattr(env, "scene", None), "object_registry", None)
    if not callable(registry):
        return None
    try:
        result = registry(key, value, default_val=None)
    except AssertionError:
        return None
    return normalize_registry_result(result, ref=ref, index=index)


def resolve_object_ref(env: Any, ref: Any) -> Any:
    scope = getattr(env.task, "object_scope", {}) or {}

    if isinstance(ref, dict):
        index = ref.get("index")
        if index is not None:
            index = int(index)
        if "bddl_name" in ref:
            return resolve_object_ref(env, str(ref["bddl_name"]))
        if "object" in ref:
            return resolve_object_ref(env, ref["object"])
        if "name" in ref:
            obj = resolve_scene_registry_object(env, "name", ref["name"], ref=ref, index=index)
            if obj is not None:
                return obj
        if "category" in ref:
            obj = resolve_scene_registry_object(env, "category", ref["category"], ref=ref, index=index)
            if obj is not None:
                return obj
        if "prim_path" in ref:
            obj = resolve_scene_registry_object(env, "prim_path", ref["prim_path"], ref=ref, index=index)
            if obj is not None:
                return obj
        raise ValueError(f"Could not resolve object reference {ref!r}")

    value = str(ref)
    if value in scope:
        obj = scope[value]
        if obj is None:
            raise ValueError(f"BDDL object {value!r} is present in scope but is not bound to a simulator object")
        return obj

    for _bddl_name, entity in scope.items():
        if entity is not None and object_name(entity) == value:
            return entity

    obj = resolve_scene_registry_object(env, "name", value, ref=ref)
    if obj is not None:
        return obj

    obj = resolve_scene_registry_object(env, "category", value, ref=ref)
    if obj is not None:
        return obj

    raise ValueError(f"Could not resolve object reference {ref!r}")


def patch_symbolic_place_near_heating_element(symbolic_cls: Any) -> None:
    """Patch an OmniGibson tensor-construction bug in PLACE_NEAR_HEATING_ELEMENT."""
    if getattr(symbolic_cls, "_evistatebench_heat_patch", False):
        return

    def _place_near_heating_element_fixed(self: Any, heat_source_obj: Any) -> Any:
        import torch as th
        from omnigibson import object_states
        from omnigibson.action_primitives.action_primitive_set_base import ActionPrimitiveError

        obj_in_hand = self._get_obj_in_hand()
        if obj_in_hand is None:
            raise ActionPrimitiveError(
                ActionPrimitiveError.Reason.PRE_CONDITION_ERROR,
                "You need to be grasping an object first to place it somewhere.",
            )

        if object_states.HeatSourceOrSink not in heat_source_obj.states:
            raise ActionPrimitiveError(
                ActionPrimitiveError.Reason.PRE_CONDITION_ERROR,
                "The target object is not a heat source or sink.",
                {"target object": heat_source_obj.name},
            )

        heat_source_state = heat_source_obj.states[object_states.HeatSourceOrSink]
        if heat_source_state.requires_inside:
            raise ActionPrimitiveError(
                ActionPrimitiveError.Reason.PRE_CONDITION_ERROR,
                "The heat source object has no explicit heating element, it just requires the cookable object to be placed inside it.",
                {"target object": heat_source_obj.name},
            )

        positions = [
            link.get_position_orientation()[0]
            for link in heat_source_state.links.values()
        ]
        heating_element_positions = th.stack(
            [position if th.is_tensor(position) else th.as_tensor(position) for position in positions]
        )

        class _TruthyTensor:
            def __init__(self, tensor: Any) -> None:
                self.tensor = tensor

            def __bool__(self) -> bool:
                return True

            def __sub__(self, other: Any) -> Any:
                return self.tensor - other

            def __rsub__(self, other: Any) -> Any:
                return other - self.tensor

        yield from self._place_with_predicate(
            heat_source_obj,
            object_states.OnTop,
            near_poses=_TruthyTensor(heating_element_positions),
            near_poses_threshold=heat_source_state.distance_threshold,
        )

    symbolic_cls._place_near_heating_element = _place_near_heating_element_fixed
    symbolic_cls._evistatebench_heat_patch = True


def make_primitive_controller(env: Any, robot: Any, args: argparse.Namespace) -> tuple[Any, Any]:
    if args.primitive_backend == "symbolic":
        from omnigibson.action_primitives.symbolic_semantic_action_primitives import (
            SymbolicSemanticActionPrimitives,
            SymbolicSemanticActionPrimitiveSet,
        )

        patch_symbolic_place_near_heating_element(SymbolicSemanticActionPrimitives)
        return SymbolicSemanticActionPrimitives(env, robot), SymbolicSemanticActionPrimitiveSet

    if args.primitive_backend == "starter":
        from omnigibson.action_primitives.starter_semantic_action_primitives import (
            StarterSemanticActionPrimitives,
            StarterSemanticActionPrimitiveSet,
        )

        return (
            StarterSemanticActionPrimitives(
                env,
                robot,
                enable_head_tracking=args.primitive_enable_head_tracking,
                task_relevant_objects_only=True,
                curobo_batch_size=args.primitive_curobo_batch_size,
                skip_curobo_initilization=args.primitive_skip_curobo_initialization,
            ),
            StarterSemanticActionPrimitiveSet,
        )

    raise ValueError(f"Unsupported primitive backend: {args.primitive_backend}")


def primitive_enum_value(enum_cls: Any, primitive_name: str) -> Any:
    try:
        return enum_cls[primitive_name]
    except KeyError as exc:
        supported = sorted(item.name for item in enum_cls)
        raise ValueError(f"Unsupported primitive {primitive_name!r}; supported primitives: {supported}") from exc


def primitive_action_summary(
    action: Any,
    *,
    step_index: int,
    row: dict[str, Any],
    primitive_name: str,
    primitive_index: int,
    primitive_backend: str,
    primitive_low_level_step: int,
    resolved_arguments: list[Any],
) -> dict[str, Any]:
    record = action_summary(action, "primitive_jsonl", step_index)
    record.update(
        {
            "primitive_backend": primitive_backend,
            "primitive_index": primitive_index,
            "primitive_jsonl_line": row.get("line_index"),
            "primitive_name": primitive_name,
            "primitive_low_level_step": primitive_low_level_step,
            "primitive_arguments": to_jsonable(row),
            "resolved_argument_names": [object_name(obj) for obj in resolved_arguments],
        }
    )
    return record


def make_action(
    robot: Any,
    step_index: int,
    args: argparse.Namespace,
    jsonl_actions: list[Any],
) -> tuple[Any, dict[str, Any]]:
    """Resolve the action for a 1-based simulator step."""
    if args.action_source == "noop":
        action = make_zero_action(robot)
    elif args.action_source == "random":
        action = robot.action_space.sample()
    elif args.action_source == "jsonl":
        action_index = step_index - 1
        if action_index >= len(jsonl_actions):
            raise ValueError(
                f"Action JSONL has {len(jsonl_actions)} actions, "
                f"but step {step_index} was requested"
            )
        action = coerce_action_for_robot(robot, jsonl_actions[action_index])
    else:
        raise ValueError(f"Unsupported action source: {args.action_source}")

    return action, action_summary(action, args.action_source, step_index)


def assert_runtime_step_budget(step_index: int, args: argparse.Namespace) -> None:
    if args.max_runtime_steps > 0 and step_index >= args.max_runtime_steps:
        raise RuntimeError(f"Reached --max-runtime-steps={args.max_runtime_steps}")


def execute_wait_primitive(
    *,
    env: Any,
    robot: Any,
    args: argparse.Namespace,
    snapshots: list[dict[str, Any]],
    step_index: int,
    row: dict[str, Any],
    primitive_index: int,
) -> int:
    wait_steps = int(row.get("steps", row.get("low_level_steps", 1)))
    if wait_steps < 0:
        raise ValueError(f"WAIT primitive steps must be non-negative, got {wait_steps}")

    for local_step in range(1, wait_steps + 1):
        assert_runtime_step_budget(step_index, args)
        step_index += 1
        action = make_zero_action(robot)
        action_record = primitive_action_summary(
            action,
            step_index=step_index,
            row=row,
            primitive_name="WAIT",
            primitive_index=primitive_index,
            primitive_backend=args.primitive_backend,
            primitive_low_level_step=local_step,
            resolved_arguments=[],
        )
        print(
            f"probe_progress=primitive_wait_step primitive_index={primitive_index} "
            f"low_level_step={local_step} runtime_step={step_index}",
            flush=True,
        )
        env.step(action)
        snapshots.append(snapshot_runtime(env, step_index=step_index, args=args, action=action_record))

    return step_index


def execute_attach_primitive(
    *,
    env: Any,
    robot: Any,
    args: argparse.Namespace,
    snapshots: list[dict[str, Any]],
    step_index: int,
    row: dict[str, Any],
    primitive_index: int,
) -> int:
    refs = primitive_argument_refs(row)
    if len(refs) != 2:
        raise ValueError(
            "ATTACH primitive expects exactly two object refs: child and parent. "
            f"Got {len(refs)} refs from row {row!r}"
        )

    child = resolve_object_ref(env, refs[0])
    parent = resolve_object_ref(env, refs[1])
    _state_name, state, state_error = find_relation_state(child, "attached")
    if state_error or state is None:
        raise ValueError(
            f"Child object {object_name(child)!r} does not expose AttachedTo/attached state: "
            f"{state_error}"
        )

    set_value = getattr(state, "set_value", None)
    if not callable(set_value):
        raise ValueError(f"AttachedTo state on {object_name(child)!r} is not settable")

    new_value = bool_option(row.get("value", row.get("attached")), True)
    success = set_value(
        parent,
        new_value,
        bypass_alignment_checking=bool_option(row.get("bypass_alignment_checking"), True),
        check_physics_stability=bool_option(row.get("check_physics_stability"), False),
        can_joint_break=bool_option(row.get("can_joint_break"), False),
    )
    if not success:
        raise RuntimeError(
            f"Failed to set attached({object_name(child)}, {object_name(parent)})={new_value}"
        )

    wait_steps = int(row.get("steps", row.get("wait_after_steps", 1)))
    if wait_steps < 1:
        wait_steps = 1
    for local_step in range(1, wait_steps + 1):
        assert_runtime_step_budget(step_index, args)
        step_index += 1
        action = make_zero_action(robot)
        action_record = primitive_action_summary(
            action,
            step_index=step_index,
            row=row,
            primitive_name="ATTACH",
            primitive_index=primitive_index,
            primitive_backend=args.primitive_backend,
            primitive_low_level_step=local_step,
            resolved_arguments=[child, parent],
        )
        action_record["local_primitive_result"] = {
            "predicate_name": "attached",
            "arguments": [object_name(child), object_name(parent)],
            "observed_value": new_value,
            "set_value_success": bool(success),
        }
        print(
            f"probe_progress=primitive_attach_step primitive_index={primitive_index} "
            f"low_level_step={local_step} runtime_step={step_index}",
            flush=True,
        )
        env.step(action)
        snapshots.append(snapshot_runtime(env, step_index=step_index, args=args, action=action_record))

    return step_index


def execute_set_state_primitive(
    *,
    env: Any,
    robot: Any,
    args: argparse.Namespace,
    snapshots: list[dict[str, Any]],
    step_index: int,
    row: dict[str, Any],
    primitive_index: int,
) -> int:
    refs = primitive_argument_refs(row)
    if len(refs) != 1:
        raise ValueError(
            "SET_STATE primitive expects exactly one object ref. "
            f"Got {len(refs)} refs from row {row!r}"
        )
    predicate_name = row.get("predicate_name", row.get("predicate", row.get("state")))
    if not predicate_name:
        raise ValueError(f"SET_STATE primitive requires predicate / predicate_name / state in row {row!r}")

    obj = resolve_object_ref(env, refs[0])
    state_name, state, state_error = find_state_by_predicate(obj, str(predicate_name))
    if state_error or state is None:
        raise ValueError(f"Object {object_name(obj)!r} does not expose state {predicate_name!r}: {state_error}")

    get_value = getattr(state, "get_value", None)
    set_value = getattr(state, "set_value", None)
    if not callable(set_value):
        raise ValueError(f"State {state_name} on {object_name(obj)!r} is not settable")

    before_value = to_jsonable(get_value()) if callable(get_value) else None
    new_value = primitive_value(row)
    success = set_value(new_value, **primitive_set_kwargs(row, allowed_keys=set()))
    after_value = to_jsonable(get_value()) if callable(get_value) else None
    if not success:
        raise RuntimeError(
            f"Failed to set {state_predicate_name(str(state_name))}({object_name(obj)})={new_value!r}"
        )

    wait_steps = int(row.get("steps", row.get("wait_after_steps", 1)))
    if wait_steps < 1:
        wait_steps = 1
    for local_step in range(1, wait_steps + 1):
        assert_runtime_step_budget(step_index, args)
        step_index += 1
        action = make_zero_action(robot)
        action_record = primitive_action_summary(
            action,
            step_index=step_index,
            row=row,
            primitive_name="SET_STATE",
            primitive_index=primitive_index,
            primitive_backend=args.primitive_backend,
            primitive_low_level_step=local_step,
            resolved_arguments=[obj],
        )
        action_record["local_primitive_result"] = {
            "predicate_name": state_predicate_name(str(state_name)),
            "arguments": [object_name(obj)],
            "previous_observed_value": before_value,
            "observed_value": after_value,
            "requested_value": to_jsonable(new_value),
            "set_value_success": bool(success),
        }
        print(
            f"probe_progress=primitive_set_state_step primitive_index={primitive_index} "
            f"low_level_step={local_step} runtime_step={step_index}",
            flush=True,
        )
        env.step(action)
        snapshots.append(snapshot_runtime(env, step_index=step_index, args=args, action=action_record))

    return step_index


def execute_set_relation_primitive(
    *,
    env: Any,
    robot: Any,
    args: argparse.Namespace,
    snapshots: list[dict[str, Any]],
    step_index: int,
    row: dict[str, Any],
    primitive_index: int,
) -> int:
    refs = primitive_argument_refs(row)
    if len(refs) != 2:
        raise ValueError(
            "SET_RELATION primitive expects exactly two object refs: source and target. "
            f"Got {len(refs)} refs from row {row!r}"
        )
    predicate_name = row.get("predicate_name", row.get("predicate", row.get("state")))
    if not predicate_name:
        raise ValueError(f"SET_RELATION primitive requires predicate / predicate_name / state in row {row!r}")

    source = resolve_object_ref(env, refs[0])
    target = resolve_object_ref(env, refs[1])
    state_name, state, state_error = find_state_by_predicate(source, str(predicate_name))
    if state_error or state is None:
        raise ValueError(
            f"Source object {object_name(source)!r} does not expose relation {predicate_name!r}: {state_error}"
        )

    get_value = getattr(state, "get_value", None)
    set_value = getattr(state, "set_value", None)
    if not callable(get_value) or not callable(set_value):
        raise ValueError(f"Relation state {state_name} on {object_name(source)!r} is not gettable/settable")

    before_value = to_jsonable(get_value(target))
    new_value = primitive_value(row)
    kwargs = primitive_set_kwargs(
        row,
        allowed_keys={
            "bypass_alignment_checking",
            "can_joint_break",
            "check_physics_stability",
            "reset_before_sampling",
            "use_trav_map",
        },
    )
    success = set_value(target, new_value, **kwargs)
    after_value = to_jsonable(get_value(target))
    if not success:
        raise RuntimeError(
            f"Failed to set {state_predicate_name(str(state_name))}"
            f"({object_name(source)}, {object_name(target)})={new_value!r}"
        )

    wait_steps = int(row.get("steps", row.get("wait_after_steps", 1)))
    if wait_steps < 1:
        wait_steps = 1
    for local_step in range(1, wait_steps + 1):
        assert_runtime_step_budget(step_index, args)
        step_index += 1
        action = make_zero_action(robot)
        action_record = primitive_action_summary(
            action,
            step_index=step_index,
            row=row,
            primitive_name="SET_RELATION",
            primitive_index=primitive_index,
            primitive_backend=args.primitive_backend,
            primitive_low_level_step=local_step,
            resolved_arguments=[source, target],
        )
        action_record["local_primitive_result"] = {
            "predicate_name": state_predicate_name(str(state_name)),
            "arguments": [object_name(source), object_name(target)],
            "previous_observed_value": before_value,
            "observed_value": after_value,
            "requested_value": to_jsonable(new_value),
            "set_value_kwargs": to_jsonable(kwargs),
            "set_value_success": bool(success),
        }
        print(
            f"probe_progress=primitive_set_relation_step primitive_index={primitive_index} "
            f"low_level_step={local_step} runtime_step={step_index}",
            flush=True,
        )
        env.step(action)
        snapshots.append(snapshot_runtime(env, step_index=step_index, args=args, action=action_record))

    return step_index


def execute_primitive_script(
    *,
    env: Any,
    robot: Any,
    args: argparse.Namespace,
    primitive_rows: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    runtime: dict[str, Any],
    start_step_index: int,
) -> int:
    controller, enum_cls = make_primitive_controller(env, robot, args)
    runtime["primitive_backend"] = args.primitive_backend
    runtime["primitive_jsonl"] = str(args.primitive_jsonl)
    runtime["primitive_count"] = len(primitive_rows)
    runtime["primitive_errors"] = []

    step_index = start_step_index
    for primitive_index, row in enumerate(primitive_rows, start=1):
        primitive_name = normalize_primitive_name(row["primitive"])
        print(
            f"probe_progress=primitive_begin primitive_index={primitive_index} primitive={primitive_name}",
            flush=True,
        )

        try:
            if primitive_name in LOCAL_PRIMITIVES:
                if primitive_name == "WAIT":
                    step_index = execute_wait_primitive(
                        env=env,
                        robot=robot,
                        args=args,
                        snapshots=snapshots,
                        step_index=step_index,
                        row=row,
                        primitive_index=primitive_index,
                    )
                    local_steps = int(row.get("steps", row.get("low_level_steps", 1)))
                elif primitive_name == "ATTACH":
                    step_index = execute_attach_primitive(
                        env=env,
                        robot=robot,
                        args=args,
                        snapshots=snapshots,
                        step_index=step_index,
                        row=row,
                        primitive_index=primitive_index,
                    )
                    local_steps = max(1, int(row.get("steps", row.get("wait_after_steps", 1))))
                elif primitive_name == "SET_STATE":
                    step_index = execute_set_state_primitive(
                        env=env,
                        robot=robot,
                        args=args,
                        snapshots=snapshots,
                        step_index=step_index,
                        row=row,
                        primitive_index=primitive_index,
                    )
                    local_steps = max(1, int(row.get("steps", row.get("wait_after_steps", 1))))
                elif primitive_name == "SET_RELATION":
                    step_index = execute_set_relation_primitive(
                        env=env,
                        robot=robot,
                        args=args,
                        snapshots=snapshots,
                        step_index=step_index,
                        row=row,
                        primitive_index=primitive_index,
                    )
                    local_steps = max(1, int(row.get("steps", row.get("wait_after_steps", 1))))
                else:
                    raise ValueError(f"Unsupported local primitive {primitive_name!r}")
                runtime.setdefault("primitive_low_level_step_counts", {})[str(primitive_index)] = local_steps
                print(
                    f"probe_progress=primitive_done primitive_index={primitive_index} primitive={primitive_name} "
                    f"runtime_step={step_index}",
                    flush=True,
                )
                continue

            primitive = primitive_enum_value(enum_cls, primitive_name)
            refs = primitive_argument_refs(row)
            resolved_arguments = [resolve_object_ref(env, ref) for ref in refs]
            generator = controller.apply_ref(primitive, *resolved_arguments, attempts=args.primitive_attempts)

            low_level_steps = 0
            for action in generator:
                low_level_steps += 1
                if (
                    args.max_primitive_low_level_steps > 0
                    and low_level_steps > args.max_primitive_low_level_steps
                ):
                    raise RuntimeError(
                        f"Primitive {primitive_name} exceeded --max-primitive-low-level-steps="
                        f"{args.max_primitive_low_level_steps}"
                    )
                assert_runtime_step_budget(step_index, args)
                step_index += 1
                action_record = primitive_action_summary(
                    action,
                    step_index=step_index,
                    row=row,
                    primitive_name=primitive_name,
                    primitive_index=primitive_index,
                    primitive_backend=args.primitive_backend,
                    primitive_low_level_step=low_level_steps,
                    resolved_arguments=resolved_arguments,
                )
                print(
                    f"probe_progress=primitive_step primitive_index={primitive_index} "
                    f"primitive={primitive_name} low_level_step={low_level_steps} runtime_step={step_index}",
                    flush=True,
                )
                env.step(action)
                snapshots.append(snapshot_runtime(env, step_index=step_index, args=args, action=action_record))

            runtime.setdefault("primitive_low_level_step_counts", {})[str(primitive_index)] = low_level_steps
            print(
                f"probe_progress=primitive_done primitive_index={primitive_index} primitive={primitive_name} "
                f"low_level_steps={low_level_steps} runtime_step={step_index}",
                flush=True,
            )
        except Exception as exc:
            error = {
                "primitive_index": primitive_index,
                "primitive_jsonl_line": row.get("line_index"),
                "primitive_name": primitive_name,
                "error": f"{type(exc).__name__}: {exc}",
            }
            runtime["primitive_errors"].append(error)
            print(
                f"probe_progress=primitive_error primitive_index={primitive_index} "
                f"primitive={primitive_name} error={error['error']}",
                flush=True,
            )
            if not args.primitive_continue_on_error:
                raise

    runtime["primitive_error_count"] = len(runtime.get("primitive_errors", []))
    runtime["primitive_runtime_steps"] = step_index - start_step_index
    return step_index


def append_kit_runtime_args(args: argparse.Namespace) -> list[str]:
    """Append Kit settings before OmniGibson launches SimulationApp."""
    kit_args: list[str] = []
    if args.disable_xr:
        kit_args.extend(
            [
                "--/app/extensions/omni.kit.xr.profile.vr/enabled=false",
                "--/app/extensions/omni.kit.xr.core/enabled=false",
                "--/app/extensions/omni.kit.xr.ui.window.viewport/enabled=false",
                "--/app/extensions/omni.kit.xr.telemetry/enabled=false",
                "--/app/xr/enabled=false",
                "--/xr/enabled=false",
            ]
        )
    for item in kit_args:
        if item not in sys.argv:
            sys.argv.append(item)
    return kit_args


def patch_omnigibson_kit_for_probe(args: argparse.Namespace) -> str | None:
    """Create a no-XR OmniGibson kit file for this probe when requested."""
    if not args.disable_xr:
        return None
    try:
        import omnigibson.simulator as simulator

        kit_dir = Path(simulator.__file__).resolve().parent
        original_name = simulator.m.KIT_FILES[(4, 5, 0)]
        original_path = kit_dir / original_name
        patched_name = "omnigibson_4_5_0_no_xr_probe.kit"
        patched_path = kit_dir / patched_name
        text = original_path.read_text(encoding="utf-8")
        text = text.replace('"omni.kit.xr.profile.vr" = {}\n', "")
        patched_path.write_text(text, encoding="utf-8")
        simulator.m.KIT_FILES[(4, 5, 0)] = patched_name
        return str(patched_path)
    except Exception as exc:
        return f"failed_to_patch_kit: {type(exc).__name__}: {exc}"


def summarize_robot(robot: Any) -> dict[str, Any]:
    position_orientation = call_method(robot, "get_position_orientation")
    joint_positions = call_method(robot, "get_joint_positions")
    joint_velocities = call_method(robot, "get_joint_velocities")
    return {
        "name": getattr(robot, "name", None),
        "class": type(robot).__name__,
        "model_name": getattr(robot, "model_name", None),
        "action_dim": getattr(robot, "action_dim", None),
        "position_orientation": position_orientation,
        "joint_positions": joint_positions,
        "joint_velocities": joint_velocities,
    }


def state_class_name(state_key: Any, state: Any) -> str:
    if hasattr(state_key, "__name__"):
        return state_key.__name__
    if isinstance(state_key, str):
        return state_key
    return type(state).__name__


def read_object_states(obj: Any, max_states: int) -> dict[str, Any]:
    states = getattr(obj, "states", {}) or {}
    readable: dict[str, Any] = {}
    unreadable: dict[str, str] = {}

    for index, (state_key, state) in enumerate(states.items()):
        if max_states > 0 and index >= max_states:
            break
        name = state_class_name(state_key, state)
        get_value = getattr(state, "get_value", None)
        if not callable(get_value):
            unreadable[name] = "missing get_value"
            continue
        try:
            readable[name] = to_jsonable(get_value())
        except Exception as exc:
            unreadable[name] = f"{type(exc).__name__}: {exc}"

    return {
        "state_count": len(states),
        "readable": readable,
        "unreadable_sample": dict(list(unreadable.items())[:10]),
        "readable_count": len(readable),
        "unreadable_count": len(unreadable),
    }


def summarize_system(system: Any) -> dict[str, Any]:
    return {
        "name": getattr(system, "name", None),
        "class": type(system).__name__,
        "initialized": getattr(system, "initialized", None),
        "n_particles": to_jsonable(getattr(system, "n_particles", None)),
    }


def active_systems(scene: Any) -> list[Any]:
    try:
        systems = getattr(scene, "active_systems", {}) or {}
        return list(systems.values())
    except Exception:
        return []


def summarize_object(obj: Any, max_states: int, bddl_name: str | None = None) -> dict[str, Any]:
    pose = call_method(obj, "get_position_orientation")
    linear_velocity = call_method(obj, "get_linear_velocity")
    angular_velocity = call_method(obj, "get_angular_velocity")
    entity_name = object_name(obj)

    return {
        "object_id": bddl_name or entity_name,
        "bddl_name": bddl_name,
        "name": entity_name,
        "class": type(obj).__name__,
        "category": getattr(obj, "category", None),
        "prim_path": str(getattr(obj, "prim_path", "")),
        "exists": to_jsonable(getattr(obj, "exists", None)),
        "position_orientation": pose,
        "linear_velocity": linear_velocity,
        "angular_velocity": angular_velocity,
        "states": read_object_states(obj, max_states=max_states),
    }


def relation_limit_reached(count: int, args: argparse.Namespace) -> bool:
    return args.max_relation_pairs > 0 and count >= args.max_relation_pairs


def parse_focused_relation(raw: str) -> dict[str, str]:
    parts = raw.split(":")
    if len(parts) != 3:
        raise ValueError(
            f"Focused relation must use predicate:source:target format, got {raw!r}"
        )
    predicate_name, source_id, target_id = (part.strip() for part in parts)
    if not predicate_name or not source_id or not target_id:
        raise ValueError(
            f"Focused relation must include predicate, source, and target, got {raw!r}"
        )
    return {
        "predicate_name": predicate_name,
        "source_id": source_id,
        "target_id": target_id,
    }


def focused_relation_specs(args: argparse.Namespace) -> list[dict[str, str]]:
    return [parse_focused_relation(raw) for raw in getattr(args, "focused_relations", []) or []]


def find_scope_entity(scope_items: list[tuple[str, Any]], entity_id: str) -> tuple[str, Any] | None:
    for scope_id, entity in scope_items:
        if str(scope_id) == entity_id or object_name(entity) == entity_id:
            return str(scope_id), entity
    return None


def find_system(systems: list[Any], system_id: str) -> Any | None:
    for system in systems:
        name = str(getattr(system, "name", ""))
        if name == system_id:
            return system
    return None


def find_relation_state(entity: Any, predicate_name: str) -> tuple[str | None, Any | None, str | None]:
    states, states_error = entity_states(entity)
    if states_error:
        return None, None, states_error
    for state_key, state in states.items():
        state_name = state_class_name(state_key, state)
        if state_predicate_name(state_name) == predicate_name:
            return state_name, state, None
    return None, None, f"missing relation state for predicate {predicate_name!r}"


def read_focused_relation_states(
    scope_items: list[tuple[str, Any]],
    systems: list[Any],
    specs: list[dict[str, str]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    relations: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    attempts = 0
    skipped_due_to_limit = 0

    for spec in specs:
        if relation_limit_reached(attempts, args):
            skipped_due_to_limit += 1
            continue

        source = find_scope_entity(scope_items, spec["source_id"])
        if source is None:
            errors.append(
                {
                    "state_name": "__focused_relation__",
                    "arguments": [spec["source_id"], spec["target_id"]],
                    "error": "source entity not found in task object scope",
                }
            )
            continue

        source_id, source_entity = source
        state_name, state, state_error = find_relation_state(source_entity, spec["predicate_name"])
        if state_error or state is None or state_name is None:
            errors.append(
                {
                    "state_name": state_name or "__focused_relation__",
                    "arguments": [source_id, spec["target_id"]],
                    "error": state_error or "relation state not found",
                }
            )
            continue

        get_value = getattr(state, "get_value", None)
        if not callable(get_value):
            errors.append(
                {
                    "state_name": state_name,
                    "arguments": [source_id, spec["target_id"]],
                    "error": "missing get_value",
                }
            )
            continue

        attempts += 1
        try:
            if state_name in OBJECT_RELATION_STATE_NAMES:
                target = find_scope_entity(scope_items, spec["target_id"])
                if target is None:
                    raise ValueError("target entity not found in task object scope")
                target_id, target_entity = target
                value = to_jsonable(get_value(target_entity))
                relations.append(
                    {
                        "state_name": state_name,
                        "predicate_name": state_predicate_name(state_name),
                        "arguments": [source_id, target_id],
                        "argument_entity_names": [object_name(source_entity), object_name(target_entity)],
                        "relation_kind": "object",
                        "observed_value": value,
                    }
                )
            elif state_name in SYSTEM_RELATION_STATE_NAMES:
                system = find_system(systems, spec["target_id"])
                if system is None:
                    raise ValueError("target system not found in active systems")
                system_name = str(getattr(system, "name", spec["target_id"]))
                value = to_jsonable(get_value(system))
                relations.append(
                    {
                        "state_name": state_name,
                        "predicate_name": state_predicate_name(state_name),
                        "arguments": [source_id, system_name],
                        "argument_entity_names": [object_name(source_entity), system_name],
                        "relation_kind": "system",
                        "observed_value": value,
                    }
                )
            else:
                raise ValueError(f"predicate {spec['predicate_name']!r} is not a relation state")
        except Exception as exc:
            errors.append(
                {
                    "state_name": state_name,
                    "arguments": [source_id, spec["target_id"]],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    return {
        "relations": relations,
        "attempt_count": attempts,
        "recorded_count": len(relations),
        "error_count": len(errors),
        "skipped_due_to_limit": skipped_due_to_limit,
        "focused_relation_count": len(specs),
        "errors_sample": errors[:20],
    }


def read_relation_states(
    scope_items: list[tuple[str, Any]],
    systems: list[Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    if not args.record_relations:
        return {
            "relations": [],
            "attempt_count": 0,
            "recorded_count": 0,
            "error_count": 0,
            "skipped_due_to_limit": 0,
            "errors_sample": [],
        }

    specs = focused_relation_specs(args)
    if specs:
        return read_focused_relation_states(scope_items, systems, specs, args)

    relations: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    attempts = 0
    skipped_due_to_limit = 0

    for source_id, source_entity in scope_items:
        states, states_error = entity_states(source_entity)
        if states_error:
            errors.append(
                {
                    "state_name": "__entity_states__",
                    "arguments": [str(source_id)],
                    "error": states_error,
                }
            )
            continue
        for state_key, state in states.items():
            state_name = state_class_name(state_key, state)
            if state_name not in OBJECT_RELATION_STATE_NAMES and state_name not in SYSTEM_RELATION_STATE_NAMES:
                continue
            get_value = getattr(state, "get_value", None)
            if not callable(get_value):
                continue

            if state_name in OBJECT_RELATION_STATE_NAMES:
                for target_id, target_entity in scope_items:
                    if target_entity is source_entity:
                        continue
                    if relation_limit_reached(attempts, args):
                        skipped_due_to_limit += 1
                        continue
                    attempts += 1
                    try:
                        value = to_jsonable(get_value(target_entity))
                        relations.append(
                            {
                                "state_name": state_name,
                                "predicate_name": state_predicate_name(state_name),
                                "arguments": [str(source_id), str(target_id)],
                                "argument_entity_names": [object_name(source_entity), object_name(target_entity)],
                                "relation_kind": "object",
                                "observed_value": value,
                            }
                        )
                    except Exception as exc:
                        errors.append(
                            {
                                "state_name": state_name,
                                "arguments": [str(source_id), str(target_id)],
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )

            if state_name in SYSTEM_RELATION_STATE_NAMES:
                for system in systems:
                    system_name = getattr(system, "name", None)
                    if not system_name:
                        continue
                    if relation_limit_reached(attempts, args):
                        skipped_due_to_limit += 1
                        continue
                    attempts += 1
                    try:
                        value = to_jsonable(get_value(system))
                        relations.append(
                            {
                                "state_name": state_name,
                                "predicate_name": state_predicate_name(state_name),
                                "arguments": [str(source_id), str(system_name)],
                                "argument_entity_names": [object_name(source_entity), str(system_name)],
                                "relation_kind": "system",
                                "observed_value": value,
                            }
                        )
                    except Exception as exc:
                        errors.append(
                            {
                                "state_name": state_name,
                                "arguments": [str(source_id), str(system_name)],
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )

    return {
        "relations": relations,
        "attempt_count": attempts,
        "recorded_count": len(relations),
        "error_count": len(errors),
        "skipped_due_to_limit": skipped_due_to_limit,
        "errors_sample": errors[:20],
    }


def summarize_goal(task: Any) -> dict[str, Any]:
    goal_options = getattr(task, "ground_goal_state_options", None)
    if not goal_options:
        return {"ok": False, "error": "task has no ground_goal_state_options"}

    try:
        from bddl.activity import evaluate_goal_conditions

        success, satisfied = evaluate_goal_conditions(goal_options[0])
        satisfied_items = satisfied.get("satisfied", [])
        unsatisfied_items = satisfied.get("unsatisfied", [])
        return {
            "ok": True,
            "success": bool(success),
            "satisfied_count": len(satisfied_items),
            "unsatisfied_count": len(unsatisfied_items),
            "satisfied_sample": [str(item) for item in satisfied_items[:8]],
            "unsatisfied_sample": [str(item) for item in unsatisfied_items[:8]],
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def summarize_task_runtime(task: Any) -> dict[str, Any]:
    conditions = getattr(task, "activity_conditions", None)
    parsed_objects = getattr(conditions, "parsed_objects", None)
    parsed_goal_conditions = getattr(conditions, "parsed_goal_conditions", None)
    parsed_initial_conditions = getattr(conditions, "parsed_initial_conditions", None)

    return {
        "class": type(task).__name__,
        "activity_name": getattr(task, "activity_name", None),
        "activity_definition_id": getattr(task, "activity_definition_id", None),
        "online_object_sampling": getattr(task, "online_object_sampling", None),
        "object_instance_to_category": to_jsonable(getattr(task, "object_instance_to_category", None)),
        "parsed_objects": to_jsonable(parsed_objects),
        "parsed_goal_condition_count": len(parsed_goal_conditions) if parsed_goal_conditions is not None else None,
        "parsed_initial_condition_count": len(parsed_initial_conditions)
        if parsed_initial_conditions is not None
        else None,
        "natural_language_initial_conditions": to_jsonable(
            getattr(task, "activity_natural_language_initial_conditions", None)
        ),
        "natural_language_goal_conditions": to_jsonable(getattr(task, "activity_natural_language_goal_conditions", None)),
        "ground_goal_option_count": len(getattr(task, "ground_goal_state_options", []) or []),
    }


def snapshot_runtime(
    env: Any,
    step_index: int,
    args: argparse.Namespace,
    action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scene_objects = list(getattr(env.scene, "objects", []) or [])
    robots = list(getattr(env, "robots", []) or [])
    object_limit = None if args.max_objects <= 0 else args.max_objects
    recorded_objects = scene_objects if object_limit is None else scene_objects[:object_limit]
    recorded_scope_items = object_scope_items(env, object_limit=object_limit)
    reverse_scope = reverse_scope_map(recorded_scope_items)
    scope_name_by_entity_name = {object_name(entity): str(name) for name, entity in recorded_scope_items}
    systems = active_systems(env.scene)
    relation_summary = read_relation_states(recorded_scope_items, systems, args=args)
    objects = [
        summarize_object(
            obj,
            max_states=args.max_states_per_object,
            bddl_name=reverse_scope.get(id(obj)) or scope_name_by_entity_name.get(object_name(obj)),
        )
        for obj in recorded_objects
    ]
    scope_records = [
        {
            "bddl_name": str(name),
            "entity_name": object_name(entity),
            "exists": to_jsonable(getattr(entity, "exists", None)),
            "is_system": to_jsonable(getattr(entity, "is_system", None)),
        }
        for name, entity in recorded_scope_items
    ]

    return {
        "episode_id": make_episode_id(args),
        "task_id": args.activity_name,
        "step_index": step_index,
        "event_time": float(step_index),
        "arrival_time": float(step_index) + args.arrival_delay,
        "action": action,
        "scene_model": args.scene_model,
        "scene_instance": task_scene_instance(args),
        "activity_name": args.activity_name,
        "activity_definition_id": args.activity_definition_id,
        "activity_instance_id": args.activity_instance_id,
        "task": summarize_task_runtime(env.task),
        "scene_object_count": len(scene_objects),
        "task_object_scope_count": len(getattr(env.task, "object_scope", {}) or {}),
        "scene_object_recorded_count": len(recorded_objects),
        "task_object_scope_recorded_count": len(recorded_scope_items),
        "robot_count": len(robots),
        "robots": [summarize_robot(robot) for robot in robots],
        "systems": [summarize_system(system) for system in systems],
        "objects": objects,
        "objects_sample": objects[:8],
        "task_object_scope": scope_records,
        "task_object_scope_sample": scope_records[:8],
        "relation_states": relation_summary["relations"],
        "relation_state_summary": {
            key: value
            for key, value in relation_summary.items()
            if key != "relations"
        },
        "goal": summarize_goal(env.task),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def call_value(call_result: dict[str, Any]) -> Any:
    if call_result.get("ok"):
        return call_result.get("value")
    return None


def make_observation(
    *,
    obs_id: str,
    snapshot: dict[str, Any],
    predicate_name: str,
    arguments: list[str] | tuple[str, ...],
    observed_value: Any,
    evidence_ref: str,
    source: str = "omnigibson_simulator_truth",
    kind: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    obs = StateObservation(
        obs_id=obs_id,
        episode_id=str(snapshot["episode_id"]),
        task_id=str(snapshot["task_id"]),
        event_time=float(snapshot["event_time"]),
        arrival_time=float(snapshot["arrival_time"]),
        source=source,
        predicate_name=predicate_name,
        arguments=tuple(str(item) for item in arguments),
        observed_value=to_jsonable(observed_value),
        confidence=1.0,
        observation_kind=kind or observation_kind(predicate_name, observed_value),
        evidence_ref=evidence_ref,
        polarity="support",
        metadata=metadata or {},
    )
    return obs.to_dict()


def add_observation(
    observations: list[dict[str, Any]],
    snapshot: dict[str, Any],
    counter: dict[str, int],
    predicate_name: str,
    arguments: list[str] | tuple[str, ...],
    observed_value: Any,
    evidence_ref: str,
    *,
    source: str = "omnigibson_simulator_truth",
    kind: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    counter["value"] += 1
    obs_id = f"og_obs_{counter['value']:08d}"
    observations.append(
        make_observation(
            obs_id=obs_id,
            snapshot=snapshot,
            predicate_name=predicate_name,
            arguments=arguments,
            observed_value=observed_value,
            evidence_ref=evidence_ref,
            source=source,
            kind=kind,
            metadata=metadata,
        )
    )


def snapshot_to_observations(
    snapshot: dict[str, Any],
    counter: dict[str, int],
    *,
    include_diagnostics: bool,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    step_index = snapshot["step_index"]
    episode_id = snapshot["episode_id"]

    for robot in snapshot.get("robots", []):
        robot_id = str(robot.get("name") or "robot")
        pose = call_value(robot.get("position_orientation", {}))
        if pose is not None:
            add_observation(
                observations,
                snapshot,
                counter,
                "robot_pose",
                [robot_id],
                pose,
                f"omnigibson://{episode_id}/step/{step_index}/robot/{robot_id}/pose",
                kind="robot_pose",
                metadata={"robot_class": robot.get("class"), "robot_model_name": robot.get("model_name")},
            )
        joint_positions = call_value(robot.get("joint_positions", {}))
        joint_velocities = call_value(robot.get("joint_velocities", {}))
        if joint_positions is not None or joint_velocities is not None:
            add_observation(
                observations,
                snapshot,
                counter,
                "joint_state",
                [robot_id],
                {"positions": joint_positions, "velocities": joint_velocities},
                f"omnigibson://{episode_id}/step/{step_index}/robot/{robot_id}/joints",
                kind="joint_state",
                metadata={"robot_class": robot.get("class"), "robot_model_name": robot.get("model_name")},
            )

    for obj in snapshot.get("objects", []):
        object_id = str(obj.get("object_id") or obj.get("name"))
        base_metadata = {
            "bddl_name": obj.get("bddl_name"),
            "entity_name": obj.get("name"),
            "category": obj.get("category"),
            "class": obj.get("class"),
            "prim_path": obj.get("prim_path"),
        }
        exists_value = obj.get("exists")
        add_observation(
            observations,
            snapshot,
            counter,
            "object_exists",
            [object_id],
            True if exists_value is None else bool(exists_value),
            f"omnigibson://{episode_id}/step/{step_index}/object/{object_id}/exists",
            kind="object_existence",
            metadata=base_metadata,
        )
        pose = call_value(obj.get("position_orientation", {}))
        if pose is not None:
            add_observation(
                observations,
                snapshot,
                counter,
                "object_pose",
                [object_id],
                pose,
                f"omnigibson://{episode_id}/step/{step_index}/object/{object_id}/pose",
                kind="object_pose",
                metadata=base_metadata,
            )
        linear_velocity = call_value(obj.get("linear_velocity", {}))
        angular_velocity = call_value(obj.get("angular_velocity", {}))
        if linear_velocity is not None or angular_velocity is not None:
            add_observation(
                observations,
                snapshot,
                counter,
                "object_velocity",
                [object_id],
                {"linear": linear_velocity, "angular": angular_velocity},
                f"omnigibson://{episode_id}/step/{step_index}/object/{object_id}/velocity",
                kind="object_velocity",
                metadata=base_metadata,
            )

        readable_states = obj.get("states", {}).get("readable", {})
        for state_name, value in readable_states.items():
            if state_name == "Joint" and (obj.get("category") == "agent" or value == []):
                continue
            predicate_name = state_predicate_name(state_name)
            if state_name in DIAGNOSTIC_STATE_NAMES and not include_diagnostics:
                continue
            if state_name == "Pose":
                continue
            kind = observation_kind(predicate_name, value)
            if kind == "simulator_diagnostic" and not include_diagnostics:
                continue
            add_observation(
                observations,
                snapshot,
                counter,
                predicate_name,
                [object_id],
                value,
                f"omnigibson://{episode_id}/step/{step_index}/object/{object_id}/state/{state_name}",
                kind=kind,
                metadata=base_metadata | {"state_name": state_name},
            )

    for relation in snapshot.get("relation_states", []):
        predicate_name = str(relation.get("predicate_name") or state_predicate_name(str(relation.get("state_name"))))
        value = relation.get("observed_value")
        kind = observation_kind(predicate_name, value)
        if kind == "simulator_diagnostic" and not include_diagnostics:
            continue
        args = [str(item) for item in relation.get("arguments", [])]
        if not args:
            continue
        add_observation(
            observations,
            snapshot,
            counter,
            predicate_name,
            args,
            value,
            f"omnigibson://{episode_id}/step/{step_index}/relation/{predicate_name}/{'/'.join(args)}",
            kind=kind,
            metadata={
                "state_name": relation.get("state_name"),
                "relation_kind": relation.get("relation_kind"),
                "argument_entity_names": relation.get("argument_entity_names"),
            },
        )

    return observations


def snapshots_to_observations(
    snapshots: list[dict[str, Any]],
    *,
    include_diagnostics: bool,
) -> list[dict[str, Any]]:
    counter = {"value": 0}
    observations: list[dict[str, Any]] = []
    for snapshot in snapshots:
        observations.extend(
            snapshot_to_observations(
                snapshot,
                counter,
                include_diagnostics=include_diagnostics,
            )
        )
    return observations


def json_value_signature(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def args_to_config(args: argparse.Namespace) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for key, value in sorted(vars(args).items()):
        if key in {"runtime_child", "child_result_json", "child_snapshots_jsonl"}:
            continue
        if isinstance(value, Path):
            config[key] = str(value)
        else:
            config[key] = to_jsonable(value)
    return config


def build_hidden_state_timeline(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert clean simulator observations into hidden state change events.

    The clean observation stream can contain repeated evidence for an unchanged
    state. The hidden timeline keeps only the first value and later change
    points for each episode-scoped state key.
    """
    last_signature_by_key: dict[tuple[str, tuple[str, ...]], str] = {}
    last_value_by_key: dict[tuple[str, tuple[str, ...]], Any] = {}
    open_event_index_by_key: dict[tuple[str, tuple[str, ...]], int] = {}
    events: list[dict[str, Any]] = []

    ordered_observations = sorted(
        observations,
        key=lambda row: (
            str(row.get("episode_id", "")),
            float(row.get("event_time", 0.0)),
            str(row.get("obs_id", "")),
        ),
    )

    for obs in ordered_observations:
        predicate_name = str(obs["predicate_name"])
        arguments = tuple(str(item) for item in obs["arguments"])
        key = (predicate_name, arguments)
        observed_value = to_jsonable(obs.get("observed_value"))
        signature = json_value_signature(observed_value)
        if last_signature_by_key.get(key) == signature:
            continue

        event_time = float(obs["event_time"])
        if key in open_event_index_by_key:
            events[open_event_index_by_key[key]]["valid_to"] = event_time

        previous_value = last_value_by_key.get(key)
        event_index = len(events) + 1
        event_type = "initial_state" if key not in last_signature_by_key else "state_change"
        event = {
            "event_id": f"og_evt_{event_index:08d}",
            "artifact_version": ARTIFACT_VERSION,
            "episode_id": str(obs["episode_id"]),
            "task_id": str(obs["task_id"]),
            "event_time": event_time,
            "event_index": event_index,
            "event_type": event_type,
            "predicate_name": predicate_name,
            "arguments": list(arguments),
            "state_key": [predicate_name, list(arguments)],
            "observed_value": observed_value,
            "truth_value": observed_value if isinstance(observed_value, bool) else None,
            "previous_observed_value": previous_value,
            "valid_from": event_time,
            "valid_to": None,
            "source_observation_id": obs.get("obs_id"),
            "source_evidence_ref": obs.get("evidence_ref"),
            "observation_kind": obs.get("observation_kind"),
            "predicate_category": obs.get("predicate_category"),
            "metadata": {
                "source": "omnigibson_simulator_truth",
                "source_observation_metadata": obs.get("metadata", {}),
            },
        }
        events.append(event)
        open_event_index_by_key[key] = len(events) - 1
        last_signature_by_key[key] = signature
        last_value_by_key[key] = observed_value

    return events


def first_snapshot(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    return snapshots[0] if snapshots else {}


def last_snapshot(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    return snapshots[-1] if snapshots else {}


def build_task_spec(
    *,
    args: argparse.Namespace,
    snapshots: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    template_summary: dict[str, Any],
) -> dict[str, Any]:
    episode_id = make_episode_id(args)
    initial = first_snapshot(snapshots)
    final = last_snapshot(snapshots)
    task_summary = initial.get("task") or final.get("task") or {}
    scope_records = initial.get("task_object_scope") or final.get("task_object_scope") or []
    predicate_vocabulary = sorted({str(row["predicate_name"]) for row in observations})
    observation_kind_counts = Counter(str(row.get("observation_kind")) for row in observations)

    return {
        "task_spec_id": f"{episode_id}__task_spec",
        "artifact_version": ARTIFACT_VERSION,
        "episode_id": episode_id,
        "task_id": args.activity_name,
        "task_family": args.activity_name,
        "task_file_id": task_scene_instance(args),
        "scene_model": args.scene_model,
        "scene_instance": task_scene_instance(args),
        "activity_name": args.activity_name,
        "activity_definition_id": args.activity_definition_id,
        "activity_instance_id": args.activity_instance_id,
        "robot_type": args.robot_type,
        "object_scope": [str(row.get("bddl_name")) for row in scope_records if row.get("bddl_name")],
        "object_scope_records": scope_records,
        "predicate_vocabulary": predicate_vocabulary,
        "observation_kind_counts": dict(observation_kind_counts),
        "timeline_event_count": len(timeline),
        "final_time": float(final.get("event_time", 0.0)) if final else 0.0,
        "goal_conditions_natural_language": task_summary.get("natural_language_goal_conditions"),
        "initial_conditions_natural_language": task_summary.get("natural_language_initial_conditions"),
        "goal_condition_count": task_summary.get("parsed_goal_condition_count"),
        "initial_condition_count": task_summary.get("parsed_initial_condition_count"),
        "object_instance_to_category": task_summary.get("object_instance_to_category"),
        "metadata": {
            "source": "omnigibson_live_simulator",
            "template": template_summary,
            "parsed_objects": task_summary.get("parsed_objects"),
        },
    }


def artifact_paths(args: argparse.Namespace) -> dict[str, Path]:
    base_dir = episode_output_dir(args)
    return {
        "episode_dir": base_dir,
        "episode_manifest": base_dir / "episode_manifest.json",
        "simulator_truth_snapshots": base_dir / "simulator_truth_snapshots.jsonl",
        "hidden_state_timeline": base_dir / "hidden_state_timeline.jsonl",
        "clean_state_observations": base_dir / "clean_state_observations.jsonl",
        "task_spec": base_dir / "task_spec.json",
        "generation_report_json": base_dir / "generation_report.json",
        "generation_report_markdown": base_dir / "generation_report.md",
        "action_trace": base_dir / "action_trace.jsonl",
    }


def string_artifact_paths(paths: dict[str, Path]) -> dict[str, str]:
    return {key: str(value) for key, value in paths.items()}


def build_action_trace(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        action = snapshot.get("action")
        if action is None:
            continue
        rows.append(
            {
                "episode_id": snapshot.get("episode_id"),
                "step_index": snapshot.get("step_index"),
                "event_time": snapshot.get("event_time"),
                "arrival_time": snapshot.get("arrival_time"),
                "action": action,
            }
        )
    return rows


def build_episode_manifest(
    *,
    args: argparse.Namespace,
    report: dict[str, Any],
    snapshots: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    task_spec: dict[str, Any],
    paths: dict[str, Path],
) -> dict[str, Any]:
    final = last_snapshot(snapshots)
    goal = final.get("goal", {}) if final else {}
    path_strings = string_artifact_paths(paths)
    path_strings.pop("episode_dir", None)

    return {
        "artifact_version": ARTIFACT_VERSION,
        "episode_id": make_episode_id(args),
        "generated_at": report.get("generated_at") or utc_now(),
        "status": report.get("status"),
        "task": {
            "task_id": args.activity_name,
            "activity_name": args.activity_name,
            "activity_definition_id": args.activity_definition_id,
            "activity_instance_id": args.activity_instance_id,
            "seed": args.seed,
            "scene_model": args.scene_model,
            "scene_instance": task_scene_instance(args),
            "task_spec_id": task_spec["task_spec_id"],
        },
        "action_source": {
            "kind": args.action_source,
            "jsonl_path": str(args.action_jsonl) if args.action_jsonl else None,
            "primitive_jsonl_path": str(args.primitive_jsonl) if args.primitive_jsonl else None,
            "primitive_backend": args.primitive_backend if args.action_source == "primitive_jsonl" else None,
            "requested_steps": args.steps,
            "max_runtime_steps": args.max_runtime_steps,
            "recorded_action_count": len(build_action_trace(snapshots)),
        },
        "recording_policy": {
            "max_objects": args.max_objects,
            "max_states_per_object": args.max_states_per_object,
            "record_relations": args.record_relations,
            "max_relation_pairs": args.max_relation_pairs,
            "focused_relations": list(getattr(args, "focused_relations", []) or []),
            "include_diagnostics_in_clean": args.include_diagnostics_in_clean,
            "arrival_delay": args.arrival_delay,
        },
        "runtime": report.get("runtime", {}),
        "counts": {
            "simulator_truth_snapshots": len(snapshots),
            "clean_state_observations": len(observations),
            "hidden_state_timeline_events": len(timeline),
            "task_object_scope": len(task_spec.get("object_scope", [])),
            "predicate_vocabulary": len(task_spec.get("predicate_vocabulary", [])),
        },
        "final_goal_summary": {
            "ok": goal.get("ok"),
            "success": goal.get("success"),
            "satisfied_count": goal.get("satisfied_count"),
            "unsatisfied_count": goal.get("unsatisfied_count"),
        },
        "artifacts": path_strings,
        "script_config": args_to_config(args),
    }


def build_generation_report(
    *,
    args: argparse.Namespace,
    report: dict[str, Any],
    snapshots: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    task_spec: dict[str, Any],
    manifest: dict[str, Any],
    paths: dict[str, Path],
) -> dict[str, Any]:
    predicate_counts = Counter(str(row["predicate_name"]) for row in observations)
    observation_kind_counts = Counter(str(row.get("observation_kind")) for row in observations)
    timeline_event_type_counts = Counter(str(row.get("event_type")) for row in timeline)
    final = last_snapshot(snapshots)

    generation_report = {
        "artifact_version": ARTIFACT_VERSION,
        "status": report.get("status"),
        "failed_phase": report.get("failed_phase"),
        "generated_at": report.get("generated_at") or utc_now(),
        "episode_id": make_episode_id(args),
        "behavior_root": str(args.behavior_root),
        "task": manifest["task"],
        "runtime": report.get("runtime", {}),
        "preflight": report.get("preflight", {}),
        "counts": manifest["counts"],
        "predicate_counts": dict(predicate_counts),
        "observation_kind_counts": dict(observation_kind_counts),
        "timeline_event_type_counts": dict(timeline_event_type_counts),
        "last_snapshot_summary": report.get("last_snapshot_summary", {}),
        "final_goal": final.get("goal", {}) if final else {},
        "task_spec_summary": {
            "task_spec_id": task_spec["task_spec_id"],
            "object_scope_count": len(task_spec.get("object_scope", [])),
            "predicate_vocabulary_count": len(task_spec.get("predicate_vocabulary", [])),
            "goal_condition_count": task_spec.get("goal_condition_count"),
        },
        "outputs": string_artifact_paths(paths),
        "error": report.get("error"),
    }
    return generation_report


def write_generation_markdown(path: Path, generation_report: dict[str, Any]) -> None:
    counts = generation_report.get("counts", {})
    outputs = generation_report.get("outputs", {})
    task = generation_report.get("task", {})
    lines = [
        "# OmniGibson Stage 3 Generation Report",
        "",
        f"- status: {generation_report.get('status')}",
        f"- failed_phase: {generation_report.get('failed_phase')}",
        f"- generated_at: {generation_report.get('generated_at')}",
        f"- episode_id: {generation_report.get('episode_id')}",
        f"- task: {task.get('activity_name')}",
        f"- scene: {task.get('scene_model')} / {task.get('scene_instance')}",
        "",
        "## Artifacts",
        "",
        f"- episode_manifest: {outputs.get('episode_manifest')}",
        f"- simulator_truth_snapshots: {outputs.get('simulator_truth_snapshots')}",
        f"- hidden_state_timeline: {outputs.get('hidden_state_timeline')}",
        f"- clean_state_observations: {outputs.get('clean_state_observations')}",
        f"- task_spec: {outputs.get('task_spec')}",
        "",
        "## Counts",
        "",
        f"- simulator_truth_snapshots: {counts.get('simulator_truth_snapshots')}",
        f"- clean_state_observations: {counts.get('clean_state_observations')}",
        f"- hidden_state_timeline_events: {counts.get('hidden_state_timeline_events')}",
        f"- task_object_scope: {counts.get('task_object_scope')}",
        f"- predicate_vocabulary: {counts.get('predicate_vocabulary')}",
        "",
        "## Runtime",
        "",
    ]

    runtime = generation_report.get("runtime", {})
    for key in ("import_ok", "env_created", "reset_ok", "requested_steps", "recorded_snapshots", "elapsed_sec"):
        lines.append(f"- {key}: {runtime.get(key)}")

    error = generation_report.get("error")
    if error:
        lines.extend(["", "## Error", "", f"- type: {error.get('type')}"])
        lines.append(f"- message: {error.get('message')}")
        lines.append("")
        lines.append("```text")
        lines.extend(error.get("traceback_tail", []))
        lines.append("```")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_stage3_artifacts(
    *,
    args: argparse.Namespace,
    report: dict[str, Any],
    snapshots: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, Any]]:
    paths = artifact_paths(args)
    paths["episode_dir"].mkdir(parents=True, exist_ok=True)

    observations = snapshots_to_observations(
        snapshots,
        include_diagnostics=args.include_diagnostics_in_clean,
    )
    timeline = build_hidden_state_timeline(observations)
    task_spec = build_task_spec(
        args=args,
        snapshots=snapshots,
        observations=observations,
        timeline=timeline,
        template_summary=report.get("preflight", {}).get("template", {}),
    )
    manifest = build_episode_manifest(
        args=args,
        report=report,
        snapshots=snapshots,
        observations=observations,
        timeline=timeline,
        task_spec=task_spec,
        paths=paths,
    )
    generation_report = build_generation_report(
        args=args,
        report=report,
        snapshots=snapshots,
        observations=observations,
        timeline=timeline,
        task_spec=task_spec,
        manifest=manifest,
        paths=paths,
    )

    write_json(paths["episode_manifest"], manifest)
    write_jsonl(paths["simulator_truth_snapshots"], snapshots)
    write_jsonl(paths["hidden_state_timeline"], timeline)
    write_jsonl(paths["clean_state_observations"], observations)
    write_jsonl(paths["action_trace"], build_action_trace(snapshots))
    write_json(paths["task_spec"], task_spec)
    write_json(paths["generation_report_json"], generation_report)
    write_generation_markdown(paths["generation_report_markdown"], generation_report)

    return string_artifact_paths(paths), generation_report


def tail_text(path: Path, max_bytes: int = 16000) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as file:
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(max(size - max_bytes, 0), os.SEEK_SET)
        return file.read().decode("utf-8", errors="replace")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    preflight = report.get("preflight", {})
    runtime = report.get("runtime", {})
    outputs = report.get("outputs", {})
    lines = [
        "# OmniGibson Stage 3 Recorder",
        "",
        f"- status: {report.get('status')}",
        f"- failed_phase: {report.get('failed_phase')}",
        f"- generated_at: {report.get('generated_at')}",
        f"- behavior_root: {report.get('behavior_root')}",
        f"- episode_manifest: {outputs.get('episode_manifest')}",
        f"- simulator_truth_snapshots: {outputs.get('simulator_truth_snapshots')}",
        f"- hidden_state_timeline: {outputs.get('hidden_state_timeline')}",
        f"- clean_state_observations: {outputs.get('clean_state_observations')}",
        "",
        "## Task Instance",
        "",
        f"- activity: {preflight.get('activity_name')}",
        f"- scene_model: {preflight.get('scene_model')}",
        f"- scene_instance: {preflight.get('scene_instance')}",
        f"- template_exists: {preflight.get('template', {}).get('exists')}",
        f"- object_scope_count: {preflight.get('template', {}).get('object_scope_count')}",
        f"- robot_pose_types: {preflight.get('template', {}).get('robot_pose_types')}",
        "",
        "## Runtime",
        "",
        f"- import_ok: {runtime.get('import_ok')}",
        f"- env_created: {runtime.get('env_created')}",
        f"- reset_ok: {runtime.get('reset_ok')}",
        f"- requested_steps: {runtime.get('requested_steps')}",
        f"- recorded_snapshots: {runtime.get('recorded_snapshots')}",
        f"- elapsed_sec: {runtime.get('elapsed_sec')}",
        "",
        "## Snapshot Summary",
        "",
    ]

    last = report.get("last_snapshot_summary") or {}
    for key in [
        "scene_object_count",
        "task_object_scope_count",
        "robot_count",
        "goal_success",
        "goal_satisfied_count",
        "goal_unsatisfied_count",
    ]:
        lines.append(f"- {key}: {last.get(key)}")

    if report.get("error"):
        lines.extend(["", "## Error", "", f"- type: {report['error'].get('type')}"])
        lines.append(f"- message: {report['error'].get('message')}")
        lines.append("")
        lines.append("```text")
        lines.extend(report["error"].get("traceback_tail", []))
        lines.append("```")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_runtime_probe(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started = time.perf_counter()
    set_runtime_seed(args.seed)
    runtime: dict[str, Any] = {
        "import_ok": False,
        "env_created": False,
        "reset_ok": False,
        "requested_steps": args.steps,
        "recorded_snapshots": 0,
        "elapsed_sec": None,
        "action_source": args.action_source,
        "seed": args.seed,
    }
    snapshots: list[dict[str, Any]] = []
    jsonl_actions: list[Any] = []
    primitive_rows: list[dict[str, Any]] = []
    if args.action_source == "jsonl":
        if args.action_jsonl is None:
            raise ValueError("--action-source jsonl requires --action-jsonl")
        jsonl_actions = load_action_jsonl(args.action_jsonl)
        runtime["action_jsonl"] = str(args.action_jsonl)
        runtime["action_jsonl_action_count"] = len(jsonl_actions)
    if args.action_source == "primitive_jsonl":
        if args.primitive_jsonl is None:
            raise ValueError("--action-source primitive_jsonl requires --primitive-jsonl")
        primitive_rows = load_primitive_jsonl(args.primitive_jsonl)
        runtime["primitive_jsonl"] = str(args.primitive_jsonl)
        runtime["primitive_count"] = len(primitive_rows)
        runtime["max_runtime_steps"] = args.max_runtime_steps
        runtime["max_primitive_low_level_steps"] = args.max_primitive_low_level_steps

    print("probe_progress=import_omnigibson_begin", flush=True)
    import omnigibson as og
    from omnigibson.macros import gm

    runtime["import_ok"] = True
    print("probe_progress=import_omnigibson_done", flush=True)
    runtime["kit_runtime_args"] = append_kit_runtime_args(args)
    print(f"probe_progress=kit_args_done args={runtime['kit_runtime_args']}", flush=True)
    runtime["patched_kit_file"] = patch_omnigibson_kit_for_probe(args)
    print(f"probe_progress=kit_patch_done file={runtime['patched_kit_file']}", flush=True)
    if og.sim is None:
        gm.ENABLE_OBJECT_STATES = True
        gm.ENABLE_FLATCACHE = args.enable_flatcache
        gm.USE_GPU_DYNAMICS = args.use_gpu_dynamics
        gm.ENABLE_TRANSITION_RULES = args.enable_transition_rules
        gm.RENDER_VIEWER_CAMERA = args.render_viewer_camera
        print(
            "probe_progress=gm_config_done "
            f"object_states={gm.ENABLE_OBJECT_STATES} "
            f"flatcache={gm.ENABLE_FLATCACHE} "
            f"gpu_dynamics={gm.USE_GPU_DYNAMICS} "
            f"transition_rules={gm.ENABLE_TRANSITION_RULES} "
            f"render_viewer_camera={gm.RENDER_VIEWER_CAMERA}",
            flush=True,
        )
    else:
        og.sim.stop()

    env = None
    try:
        print("probe_progress=environment_create_begin", flush=True)
        env = og.Environment(configs=build_env_config(args))
        runtime["env_created"] = True
        print("probe_progress=environment_create_done", flush=True)
        print("probe_progress=env_reset_begin", flush=True)
        env.reset()
        runtime["reset_ok"] = True
        print("probe_progress=env_reset_done", flush=True)
        snapshots.append(snapshot_runtime(env, step_index=0, args=args, action=None))

        robot = env.robots[0]
        if args.action_source == "primitive_jsonl":
            final_step_index = execute_primitive_script(
                env=env,
                robot=robot,
                args=args,
                primitive_rows=primitive_rows,
                snapshots=snapshots,
                runtime=runtime,
                start_step_index=0,
            )
            runtime["final_step_index"] = final_step_index
        else:
            for step_index in range(1, args.steps + 1):
                action, action_record = make_action(robot, step_index, args, jsonl_actions)
                print(f"probe_progress=env_step_begin step={step_index}", flush=True)
                env.step(action)
                print(f"probe_progress=env_step_done step={step_index}", flush=True)
                snapshots.append(snapshot_runtime(env, step_index=step_index, args=args, action=action_record))

        runtime["recorded_snapshots"] = len(snapshots)
        return runtime, snapshots
    finally:
        runtime["elapsed_sec"] = round(time.perf_counter() - started, 3)
        try:
            og.clear()
        except Exception:
            pass


def child_command(args: argparse.Namespace, result_path: Path, snapshots_path: Path) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--runtime-child",
        "--child-result-json",
        str(result_path),
        "--child-snapshots-jsonl",
        str(snapshots_path),
        "--behavior-root",
        str(args.behavior_root),
        "--output-dir",
        str(args.output_dir),
        "--activity-name",
        args.activity_name,
        "--scene-model",
        args.scene_model,
        "--activity-definition-id",
        str(args.activity_definition_id),
        "--activity-instance-id",
        str(args.activity_instance_id),
        "--robot-type",
        args.robot_type,
        "--steps",
        str(args.steps),
        "--max-objects",
        str(args.max_objects),
        "--max-states-per-object",
        str(args.max_states_per_object),
        "--viewer-width",
        str(args.viewer_width),
        "--viewer-height",
        str(args.viewer_height),
        "--device",
        args.device,
        "--action-source",
        args.action_source,
        "--arrival-delay",
        str(args.arrival_delay),
        "--max-runtime-steps",
        str(args.max_runtime_steps),
        "--max-relation-pairs",
        str(args.max_relation_pairs),
        "--primitive-backend",
        args.primitive_backend,
        "--primitive-attempts",
        str(args.primitive_attempts),
        "--max-primitive-low-level-steps",
        str(args.max_primitive_low_level_steps),
        "--primitive-curobo-batch-size",
        str(args.primitive_curobo_batch_size),
    ]
    if args.episode_id:
        command.extend(["--episode-id", args.episode_id])
    if args.seed is not None:
        command.extend(["--seed", str(args.seed)])
    if args.action_jsonl:
        command.extend(["--action-jsonl", str(args.action_jsonl)])
    if args.primitive_jsonl:
        command.extend(["--primitive-jsonl", str(args.primitive_jsonl)])
    for focused_relation in getattr(args, "focused_relations", []) or []:
        command.extend(["--focused-relation", focused_relation])
    if args.include_diagnostics_in_clean:
        command.append("--include-diagnostics-in-clean")
    if args.primitive_continue_on_error:
        command.append("--primitive-continue-on-error")
    if args.primitive_enable_head_tracking:
        command.append("--primitive-enable-head-tracking")
    if args.primitive_skip_curobo_initialization:
        command.append("--primitive-skip-curobo-initialization")
    if not args.use_primitive_robot_config:
        command.append("--no-primitive-robot-config")
    if args.full_scene:
        command.append("--full-scene")
    if args.load_structure_categories:
        command.append("--load-structure-categories")
    if args.record_relations:
        command.append("--record-relations")
    if args.use_gpu_dynamics:
        command.append("--use-gpu-dynamics")
    if args.enable_transition_rules:
        command.append("--enable-transition-rules")
    if args.enable_flatcache:
        command.append("--enable-flatcache")
    if args.render_viewer_camera:
        command.append("--render-viewer-camera")
    if args.enable_seg_map:
        command.extend(["--enable-seg-map", "--seg-map-resolution", str(args.seg_map_resolution)])
    if not args.use_presampled_robot_pose:
        command.append("--no-presampled-robot-pose")
    if not args.disable_xr:
        command.append("--no-disable-xr")
    return command


def run_runtime_probe_child_process(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    """Run OmniGibson in a child process so a segfault still leaves a report."""
    args.output_dir.mkdir(parents=True, exist_ok=True)
    child_result_path = args.output_dir / "omnigibson_recorder_probe_child_result.json"
    child_snapshots_path = args.output_dir / "omnigibson_recorder_probe_child_steps.jsonl"
    child_log_path = args.output_dir / "omnigibson_recorder_probe_child.log"
    for path in (child_result_path, child_snapshots_path, child_log_path):
        if path.exists():
            path.unlink()

    env_summary = configure_behavior_paths(args.behavior_root)
    env = os.environ.copy()
    env["PYTHONFAULTHANDLER"] = "1"
    env["EVISTATE_DEBUG_SCENE_LOAD"] = "1"
    pythonpath_prefix = env_summary["PYTHONPATH_PREFIX"]
    env["PYTHONPATH"] = (
        pythonpath_prefix
        if not env.get("PYTHONPATH")
        else pythonpath_prefix + os.pathsep + env["PYTHONPATH"]
    )

    runtime: dict[str, Any] = {
        "import_ok": False,
        "env_created": False,
        "reset_ok": False,
        "requested_steps": args.steps,
        "recorded_snapshots": 0,
        "child_process": True,
        "child_log": str(child_log_path),
        "child_result_json": str(child_result_path),
        "child_returncode": None,
    }

    command = child_command(args, child_result_path, child_snapshots_path)
    try:
        with child_log_path.open("w", encoding="utf-8") as log_file:
            proc = subprocess.run(
                command,
                cwd=str(REPO_ROOT),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=args.runtime_timeout,
                check=False,
            )
        runtime["child_returncode"] = proc.returncode
    except subprocess.TimeoutExpired:
        runtime["child_returncode"] = None
        runtime["child_timeout_sec"] = args.runtime_timeout
        return (
            runtime,
            [],
            {
                "type": "TimeoutExpired",
                "message": f"Runtime child exceeded {args.runtime_timeout} seconds",
                "traceback_tail": tail_text(child_log_path).splitlines()[-80:],
            },
        )

    child_data: dict[str, Any] = {}
    if child_result_path.exists():
        child_data = read_json(child_result_path)
        runtime.update(child_data.get("runtime", {}))
        runtime["child_returncode"] = proc.returncode

    runtime["child_log_tail"] = tail_text(child_log_path).splitlines()[-80:]
    snapshots = read_jsonl(child_snapshots_path)

    if child_data.get("status") == "PASS":
        if proc.returncode != 0:
            runtime["child_shutdown_warning"] = {
                "type": "NonZeroReturnAfterPass",
                "message": (
                    "Runtime child wrote PASS result and snapshots, but exited non-zero during shutdown. "
                    f"Keeping episode artifacts; child return code was {proc.returncode}."
                ),
                "returncode": proc.returncode,
            }
        return runtime, snapshots, None

    child_error = child_data.get("error") if child_data else None
    if child_error:
        error = child_error
    else:
        error = {
            "type": "RuntimeChildProcessError",
            "message": f"Runtime child exited with return code {proc.returncode}",
            "traceback_tail": runtime["child_log_tail"],
        }
    return runtime, snapshots, error


def run_as_runtime_child(args: argparse.Namespace) -> int:
    if args.child_result_json is None or args.child_snapshots_jsonl is None:
        raise ValueError("--runtime-child requires --child-result-json and --child-snapshots-jsonl")

    faulthandler.enable()
    configure_behavior_paths(args.behavior_root)
    result: dict[str, Any] = {
        "status": "FAIL",
        "generated_at": utc_now(),
        "runtime": {},
        "error": None,
    }
    snapshots: list[dict[str, Any]] = []
    try:
        runtime, snapshots = run_runtime_probe(args)
        result["runtime"] = runtime
        result["status"] = "PASS"
    except Exception as exc:
        result["error"] = compact_error(exc)

    args.child_result_json.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.child_result_json, result)
    write_jsonl(args.child_snapshots_jsonl, snapshots)
    print(f"child_status={result['status']}")
    return 0 if result["status"] == "PASS" else 1


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    template_path = expected_task_template_path(args)
    env_summary = configure_behavior_paths(args.behavior_root)
    preflight = {
        "activity_name": args.activity_name,
        "scene_model": args.scene_model,
        "activity_definition_id": args.activity_definition_id,
        "activity_instance_id": args.activity_instance_id,
        "seed": args.seed,
        "scene_instance": task_scene_instance(args),
        "template": summarize_task_template(template_path),
        "env": env_summary,
        "vulkan": probe_vulkan_summary(),
    }

    report: dict[str, Any] = {
        "status": "FAIL",
        "failed_phase": None,
        "generated_at": utc_now(),
        "repo_root": str(REPO_ROOT),
        "behavior_root": str(args.behavior_root),
        "preflight": preflight,
        "runtime": {},
        "last_snapshot_summary": {},
        "error": None,
        "outputs": {},
    }

    if not template_path.exists():
        report["failed_phase"] = "preflight_template_missing"
        report["error"] = {
            "type": "FileNotFoundError",
            "message": f"Cached task template does not exist: {template_path}",
            "traceback_tail": [],
        }
        return report, []

    report["failed_phase"] = "runtime_child_process"
    runtime, snapshots, error = run_runtime_probe_child_process(args)
    report["runtime"] = runtime
    if error is not None:
        report["error"] = error
        return report, snapshots

    report["status"] = "PASS"
    report["failed_phase"] = None

    if snapshots:
        last = snapshots[-1]
        goal = last.get("goal", {})
        report["last_snapshot_summary"] = {
            "scene_object_count": last.get("scene_object_count"),
            "task_object_scope_count": last.get("task_object_scope_count"),
            "robot_count": last.get("robot_count"),
            "goal_success": goal.get("success"),
            "goal_satisfied_count": goal.get("satisfied_count"),
            "goal_unsatisfied_count": goal.get("unsatisfied_count"),
        }
    return report, snapshots



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--behavior-root", type=Path, default=DEFAULT_BEHAVIOR_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    # Keep the default smoke probe small; larger tasks can still be selected via CLI flags.
    parser.add_argument("--activity-name", default="clean_a_patio")
    parser.add_argument("--scene-model", default="house_double_floor_lower")
    parser.add_argument("--activity-definition-id", type=int, default=0)
    parser.add_argument("--activity-instance-id", type=int, default=0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--robot-type", default="Fetch")
    parser.add_argument("--episode-id", default=None)
    parser.add_argument(
        "--episode-output-dir",
        type=Path,
        default=None,
        help="Directory for formal stage-3 episode artifacts. Defaults to output-dir/episodes/<episode_id>.",
    )
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--action-source", choices=["noop", "random", "jsonl", "primitive_jsonl"], default="noop")
    parser.add_argument("--action-jsonl", type=Path, default=None)
    parser.add_argument(
        "--primitive-jsonl",
        type=Path,
        default=None,
        help=(
            "Semantic primitive script JSONL. Each row can be like "
            "{\"primitive\":\"OPEN\", \"object\":\"microwave.n.02_1\"}."
        ),
    )
    parser.add_argument("--primitive-backend", choices=["symbolic", "starter"], default="symbolic")
    parser.add_argument("--primitive-attempts", type=int, default=3)
    parser.add_argument(
        "--max-primitive-low-level-steps",
        type=int,
        default=250,
        help="Per-primitive low-level step budget; 0 disables this guard.",
    )
    parser.add_argument(
        "--max-runtime-steps",
        type=int,
        default=1000,
        help="Total low-level runtime step budget for primitive_jsonl; 0 disables this guard.",
    )
    parser.add_argument(
        "--primitive-continue-on-error",
        action="store_true",
        help="Record primitive errors in runtime report and continue with later primitives.",
    )
    parser.add_argument(
        "--primitive-enable-head-tracking",
        action="store_true",
        help="Only used by starter backend. Disabled by default for headless recording.",
    )
    parser.add_argument(
        "--primitive-skip-curobo-initialization",
        action="store_true",
        help="Only used by starter backend. Mostly useful for debugging non-planning primitives.",
    )
    parser.add_argument("--primitive-curobo-batch-size", type=int, default=3)
    parser.add_argument(
        "--no-primitive-robot-config",
        dest="use_primitive_robot_config",
        action="store_false",
        help="Do not auto-load r1_primitives.yaml / tiago_primitives.yaml in primitive_jsonl mode.",
    )
    parser.add_argument("--arrival-delay", type=float, default=0.0)
    parser.add_argument(
        "--include-diagnostics-in-clean",
        action="store_true",
        help="Keep simulator diagnostic states in clean_state_observations.jsonl.",
    )
    parser.add_argument("--max-objects", type=int, default=12, help="Maximum objects to serialize; 0 records all.")
    parser.add_argument(
        "--max-states-per-object",
        type=int,
        default=16,
        help="Maximum object states to read per object; 0 records all readable states.",
    )
    parser.add_argument("--record-relations", action="store_true")
    parser.add_argument("--max-relation-pairs", type=int, default=0, help="Maximum relation checks; 0 means no limit.")
    parser.add_argument(
        "--focused-relation",
        dest="focused_relations",
        action="append",
        default=[],
        help="Only record this relation, using predicate:source:target. Can be repeated.",
    )
    parser.add_argument("--full-scene", action="store_true")
    parser.add_argument("--load-structure-categories", action="store_true")
    parser.add_argument("--viewer-width", type=int, default=640)
    parser.add_argument("--viewer-height", type=int, default=480)
    parser.add_argument("--device", default="none", help="Use 'none' for OmniGibson default CPU/device selection.")
    parser.add_argument("--use-gpu-dynamics", action="store_true")
    parser.add_argument("--enable-transition-rules", action="store_true")
    parser.add_argument(
        "--enable-flatcache",
        action="store_true",
        help="Match OmniGibson learning/eval headless settings by enabling flatcache.",
    )
    parser.add_argument(
        "--render-viewer-camera",
        action="store_true",
        help="Create OmniGibson's viewer camera. Disabled by default for state-only headless recording.",
    )
    parser.add_argument(
        "--enable-seg-map",
        action="store_true",
        help="Load OmniGibson's room segmentation map. Disabled by default for state-only headless recording.",
    )
    parser.add_argument("--seg-map-resolution", type=float, default=1.0)
    parser.add_argument("--no-presampled-robot-pose", dest="use_presampled_robot_pose", action="store_false")
    parser.add_argument("--no-disable-xr", dest="disable_xr", action="store_false")
    parser.add_argument(
        "--runtime-timeout",
        type=int,
        default=600,
        help="Child process timeout in seconds. Real BEHAVIOR tasks can take several minutes to reset.",
    )
    parser.add_argument("--runtime-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--child-result-json", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--child-snapshots-jsonl", type=Path, default=None, help=argparse.SUPPRESS)
    parser.set_defaults(use_presampled_robot_pose=True)
    parser.set_defaults(disable_xr=True)
    parser.set_defaults(use_primitive_robot_config=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.runtime_child:
        return run_as_runtime_child(args)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    report_path = args.output_dir / "omnigibson_recorder_probe.json"
    markdown_path = args.output_dir / "omnigibson_recorder_probe.md"
    snapshots_path = args.output_dir / "omnigibson_recorder_probe_steps.jsonl"

    report, snapshots = build_report(args)
    artifact_outputs, _generation_report = write_stage3_artifacts(
        args=args,
        report=report,
        snapshots=snapshots,
    )
    report["outputs"] = {
        "compat_report_json": str(report_path),
        "compat_report_markdown": str(markdown_path),
        "compat_step_snapshots_jsonl": str(snapshots_path),
        **artifact_outputs,
    }

    write_json(report_path, report)
    write_jsonl(snapshots_path, snapshots)
    write_markdown(markdown_path, report)

    print(f"status={report['status']}")
    print(f"episode_dir={artifact_outputs['episode_dir']}")
    print(f"generation_report={artifact_outputs['generation_report_json']}")
    print(f"simulator_truth_snapshots={artifact_outputs['simulator_truth_snapshots']}")
    print(f"hidden_state_timeline={artifact_outputs['hidden_state_timeline']}")
    print(f"clean_state_observations={artifact_outputs['clean_state_observations']}")
    print(f"compat_report={report_path}")
    if report.get("failed_phase"):
        print(f"failed_phase={report['failed_phase']}")
    if report.get("error"):
        print(f"error={report['error'].get('type')}: {report['error'].get('message')}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
