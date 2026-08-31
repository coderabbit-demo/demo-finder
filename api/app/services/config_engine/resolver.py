"""Config resolution per the Indeed draft spec.

One principle: inheritance-by-default via first-writer-wins while walking from
the repo outward. Two tiers bracket the walk: schema defaults (final fill) and
global overrides (final overwrite). `inheritance: false` stops the walk;
`remote_config` is an exclusive, non-inheriting redirect.

v1 consumes this minimally (fork engine validates generated configs against
schema defaults); v2's Config Lab UI drives it interactively.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Config = dict[str, Any]

_LIST_IDENTITY_KEYS = ("path", "name", "id", "key", "label")


@dataclass
class ConfigNode:
    file_name: str = ""
    file_path: str = ""
    config: Config = field(default_factory=dict)  # minus remote_config/includes/inheritance keys
    parent: "ConfigNode | None" = None            # repo -> central -> higher centrals -> org -> workspace
    remote: "ConfigNode | None" = None            # exclusive: remote XOR (config + includes)
    includes: list["ConfigNode"] = field(default_factory=list)  # last-listed wins
    inherits: bool = True                          # inheritance: false stops the upward walk


def _item_identity(item: Any) -> Any:
    if isinstance(item, dict):
        for k in _LIST_IDENTITY_KEYS:
            if k in item:
                return (k, item[k])
        return ("__repr__", repr(sorted(item.items())))
    return ("__val__", item)


def merge_lists(base_list: list | None, source_list: list | None) -> list:
    """Union: base (child) items first, then source items with new identity."""
    result = list(base_list or [])
    seen = {_item_identity(i) for i in result}
    for item in source_list or []:
        if _item_identity(item) not in seen:
            result.append(item)
            seen.add(_item_identity(item))
    return result


def fill_gaps(base: Config, source: Config) -> Config:
    """Fill only what is unset, from a lower-precedence source. `base` wins."""
    result = dict(base)
    for key, sval in (source or {}).items():
        bval = result.get(key)
        if isinstance(sval, list) or isinstance(bval, list):
            result[key] = merge_lists(bval if isinstance(bval, list) else None,
                                      sval if isinstance(sval, list) else None)
        elif isinstance(sval, dict):
            result[key] = fill_gaps(bval if isinstance(bval, dict) else {}, sval)
        else:
            if key not in result:
                result[key] = sval
    return result


def apply_overrides(base: Config, overrides: Config) -> Config:
    """Enforce: overwrite unconditionally (whole lists included). Applied last."""
    result = dict(base)
    for key, oval in (overrides or {}).items():
        if isinstance(oval, dict):
            bval = result.get(key)
            result[key] = apply_overrides(bval if isinstance(bval, dict) else {}, oval)
        else:
            result[key] = oval
    return result


def accumulate(config: Config, node: ConfigNode | None) -> Config:
    """Recursive upward walk, first writer wins."""
    if node is None:
        return config
    if node.remote is not None:
        return accumulate(config, node.remote)          # non-inheriting redirect
    config = fill_gaps(config, node.config)             # this node's keys outrank everything below
    for include in reversed(node.includes):             # last-listed wins
        config = accumulate(config, include)            # includes outrank the parent
    if not node.inherits:                               # opt-out stops the walk here
        return config
    return accumulate(config, node.parent)


def get_repo_config(repo_node: ConfigNode, schema_defaults: Config,
                    global_overrides: Config | None = None) -> Config:
    config = accumulate({}, repo_node)
    config = fill_gaps(config, schema_defaults)          # universal final fill
    config = apply_overrides(config, global_overrides or {})  # enforced final overwrite
    return config


def resolve_with_trace(repo_node: ConfigNode, schema_defaults: Config,
                       global_overrides: Config | None = None) -> dict[str, Any]:
    """Resolved config plus a flat per-key 'won by' trace (drives the Config Lab UI)."""
    trace: dict[str, str] = {}

    def flatten(cfg: Config, prefix: str = "") -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in cfg.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(flatten(v, path))
            else:
                out[path] = v
        return out

    def walk(node: ConfigNode | None, claimed: set[str]) -> None:
        if node is None:
            return
        if node.remote is not None:
            walk(node.remote, claimed)
            return
        for path in flatten(node.config):
            if path not in claimed:
                claimed.add(path)
                trace[path] = node.file_path or node.file_name or "unnamed"
        for include in reversed(node.includes):
            walk(include, claimed)
        if node.inherits:
            walk(node.parent, claimed)

    claimed: set[str] = set()
    walk(repo_node, claimed)
    for path in flatten(schema_defaults):
        if path not in claimed:
            trace[path] = "schema default"
    for path in flatten(global_overrides or {}):
        trace[path] = "global override"

    resolved = get_repo_config(repo_node, schema_defaults, global_overrides)
    return {"resolved": resolved, "won_by": trace}
