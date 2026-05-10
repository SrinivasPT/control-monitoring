"""Group decomposer — translates control.yaml into a group manifest.

This is the first LLM-assisted step in the Build phase.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from src.decomposer.llm_client import LLMClient, LLMError
from src.models.control import ControlFile
from src.models.decomposition import GroupDefinition, GroupManifest
from src.utils.filesystem import ensure_dir, file_exists, load_yaml
from src.utils.logging import get_logger

log = get_logger(__name__)

# JSON Schema that the LLM must conform to
_GROUP_MANIFEST_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "datasets": {"type": "array", "items": {"type": "string"}},
                    "checks": {"type": "array", "items": {"type": "string"}},
                    "execution_order": {"type": "integer"},
                },
                "required": [
                    "id",
                    "name",
                    "description",
                    "datasets",
                    "checks",
                    "execution_order",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["groups"],
    "additionalProperties": False,
}


def _load_system_prompt() -> str:
    prompt_path = Path(__file__).parent / "prompts" / "decompose_groups.txt"
    return prompt_path.read_text(encoding="utf-8").strip()


def _build_user_prompt(control: ControlFile) -> str:
    """Serialise the control definition as the LLM user message."""
    data = control.model_dump()
    return (
        "Decompose the following control into logical execution groups.\n\n"
        "Control definition (YAML):\n"
        f"```yaml\n{yaml.dump(data, default_flow_style=False, allow_unicode=True)}\n```"
    )


def _validate_manifest(manifest: GroupManifest, control: ControlFile) -> list[str]:
    """Return a list of validation error messages (empty = valid)."""
    errors: list[str] = []
    known_check_ids = {c.id for c in control.checks}
    known_dataset_ids = {d.id for d in control.datasets}

    seen_orders: set[int] = set()
    seen_ids: set[str] = set()

    for g in manifest.groups:
        if g.id in seen_ids:
            errors.append(f"Duplicate group id: {g.id}")
        seen_ids.add(g.id)

        if g.execution_order in seen_orders:
            errors.append(f"Duplicate execution_order: {g.execution_order}")
        seen_orders.add(g.execution_order)

        for cid in g.checks:
            if cid not in known_check_ids:
                errors.append(f"Group '{g.id}' references unknown check_id: '{cid}'")

        for did in g.datasets:
            if did not in known_dataset_ids:
                errors.append(f"Group '{g.id}' references unknown dataset: '{did}'")

    return errors


def decompose_groups(
    control: ControlFile,
    controls_dir: Path,
    llm_client: LLMClient,
    force: bool = False,
) -> GroupManifest:
    """Generate (or load) the group manifest for *control*.

    Args:
        control:       Parsed ControlFile.
        controls_dir:  Root controls/ directory.
        llm_client:    Configured LLM client.
        force:         If True, delete existing manifest and regenerate.

    Returns:
        A validated GroupManifest.
    """
    manifest_path = controls_dir / control.control.id / "decomposition.yaml"

    if manifest_path.exists() and not force:
        log.info(
            f"[{control.control.id}] decomposition.yaml exists — loading (skip LLM call)."
        )
        raw = load_yaml(manifest_path)
        return GroupManifest.model_validate(raw)

    if force and manifest_path.exists():
        manifest_path.unlink()
        log.info(
            f"[{control.control.id}] --force: deleted existing decomposition.yaml."
        )

    log.info(f"[{control.control.id}] Calling LLM to decompose groups ...")

    system_prompt = _load_system_prompt()
    user_prompt = _build_user_prompt(control)

    raw_response = llm_client.call_structured(
        system_prompt, user_prompt, _GROUP_MANIFEST_SCHEMA
    )

    # Build model
    now = datetime.now(timezone.utc).isoformat()
    groups = [GroupDefinition(**g) for g in raw_response["groups"]]
    manifest = GroupManifest(
        control_id=control.control.id,
        generated_at=now,
        generator="llm",
        groups=groups,
    )

    # Validate
    errors = _validate_manifest(manifest, control)
    if errors:
        raise ValueError(
            f"Group manifest for '{control.control.id}' failed validation:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    # Write (idempotent — we already deleted if force)
    ensure_dir(manifest_path.parent)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        data = manifest.model_dump()
        data["_comment"] = (
            "Generated by group_decomposer. MANUALLY CORRECTABLE — "
            "will not be overwritten if this file exists."
        )
        yaml.dump(
            data, fh, default_flow_style=False, allow_unicode=True, sort_keys=False
        )

    log.info(f"[{control.control.id}] decomposition.yaml written → {manifest_path}")
    return manifest
