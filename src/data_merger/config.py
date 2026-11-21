"""Optional TOML config: header overrides, thresholds, conflict rules, source priority."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

RULES = ("most_recent", "most_complete", "most_common", "source_priority")


@dataclass
class Config:
    auto_threshold: float = 0.88
    review_threshold: float = 0.70
    dayfirst: bool = False
    default_rule: str = "most_recent"
    # A newer row is no better at spelling a name, so names go by agreement between rows:
    # one typo is outvoted, and a nickname counts as a vote for the full name.
    column_rules: dict[str, str] = field(
        default_factory=lambda: {"first_name": "most_common", "last_name": "most_common"}
    )
    source_priority: list[str] = field(default_factory=list)
    mapping: dict[str, dict[str, str]] = field(default_factory=dict)
    max_block_size: int = 400
    max_cluster_size: int = 12
    one_per_source: bool = False
    strong_key_guard: bool = True
    lineage: bool = True

    def rule_for(self, column: str) -> str:
        return self.column_rules.get(column, self.default_rule)

    def validate(self) -> None:
        if not 0 < self.review_threshold <= self.auto_threshold <= 1:
            raise ValueError("Thresholds must satisfy 0 < review <= auto <= 1")
        for column, rule in {**self.column_rules, "default": self.default_rule}.items():
            if rule not in RULES:
                raise ValueError(f"Unknown rule '{rule}' for {column}. Use: {', '.join(RULES)}")


def load_config(path: str | Path | None) -> Config:
    config = Config()
    if path is None:
        return config
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    thresholds = data.get("thresholds", {})
    config.auto_threshold = float(thresholds.get("auto", config.auto_threshold))
    config.review_threshold = float(thresholds.get("review", config.review_threshold))
    options = data.get("options", {})
    config.dayfirst = bool(options.get("dayfirst", config.dayfirst))
    config.max_block_size = int(options.get("max_block_size", config.max_block_size))
    config.lineage = bool(options.get("lineage", config.lineage))
    config.max_cluster_size = int(options.get("max_cluster_size", config.max_cluster_size))
    config.one_per_source = bool(options.get("one_per_source", config.one_per_source))
    config.strong_key_guard = bool(options.get("strong_key_guard", config.strong_key_guard))
    rules = dict(data.get("rules", {}))
    config.default_rule = rules.pop("default", config.default_rule)
    config.column_rules.update(rules)
    config.source_priority = list(data.get("source_priority", {}).get("order", []))
    config.mapping = {name: dict(cols) for name, cols in data.get("mapping", {}).items()}
    config.validate()
    return config
