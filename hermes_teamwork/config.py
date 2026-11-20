"""
hermes_teamwork.config
~~~~~~~~~~~~~~~~~~~~~~
Configuration loader and ConfigDict for Teamwork framework.
Supports YAML file configuration and environment variable overrides.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Union


class ConfigDict(dict):
    """
    Configuration dictionary supporting both mapping item access (cfg['runner'])
    and attribute access (cfg.runner, cfg.max_milestone_iterations).
    Maintains bidirectional alias between max_iterations and max_milestone_iterations,
    as well as between base_url and api_base.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.update(*args, **kwargs)

    def update(self, *args: Any, **kwargs: Any) -> None:
        other = dict(*args, **kwargs)
        for k, v in other.items():
            self[k] = v

    def __getattr__(self, name: str) -> Any:
        if name in self:
            return self[name]
        if name == "max_milestone_iterations":
            return self.get("max_milestone_iterations", self.get("max_iterations", 4))
        if name == "max_iterations":
            return self.get("max_iterations", self.get("max_milestone_iterations", 4))
        if name == "api_base":
            return self.get("api_base", self.get("base_url", "http://localhost:20128/v1"))
        if name == "base_url":
            return self.get("base_url", self.get("api_base", "http://localhost:20128/v1"))
        raise AttributeError(f"'ConfigDict' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value
        if name == "max_iterations":
            dict.__setitem__(self, "max_milestone_iterations", value)
        elif name == "max_milestone_iterations":
            dict.__setitem__(self, "max_iterations", value)
        elif name == "base_url":
            dict.__setitem__(self, "api_base", value)
        elif name == "api_base":
            dict.__setitem__(self, "base_url", value)

    def __delattr__(self, name: str) -> None:
        if name in self:
            del self[name]
            if name == "max_iterations" and "max_milestone_iterations" in self:
                dict.__delitem__(self, "max_milestone_iterations")
            elif name == "max_milestone_iterations" and "max_iterations" in self:
                dict.__delitem__(self, "max_iterations")
            elif name == "base_url" and "api_base" in self:
                dict.__delitem__(self, "api_base")
            elif name == "api_base" and "base_url" in self:
                dict.__delitem__(self, "base_url")
        else:
            raise AttributeError(f"'ConfigDict' object has no attribute '{name}'")

    def __getitem__(self, key: str) -> Any:
        if key in self:
            return super().__getitem__(key)
        if key == "max_milestone_iterations" and "max_iterations" in self:
            return super().__getitem__("max_iterations")
        if key == "max_iterations" and "max_milestone_iterations" in self:
            return super().__getitem__("max_milestone_iterations")
        if key == "api_base" and "base_url" in self:
            return super().__getitem__("base_url")
        if key == "base_url" and "api_base" in self:
            return super().__getitem__("api_base")
        if key in ("max_iterations", "max_milestone_iterations"):
            return 4
        if key in ("base_url", "api_base"):
            return "http://localhost:20128/v1"
        return super().__getitem__(key)

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        if key == "max_iterations":
            super().__setitem__("max_milestone_iterations", value)
        elif key == "max_milestone_iterations":
            super().__setitem__("max_iterations", value)
        elif key == "base_url":
            super().__setitem__("api_base", value)
        elif key == "api_base":
            super().__setitem__("base_url", value)

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key)
        if key == "max_iterations" and "max_milestone_iterations" in self:
            super().__delitem__("max_milestone_iterations")
        elif key == "max_milestone_iterations" and "max_iterations" in self:
            super().__delitem__("max_iterations")
        elif key == "base_url" and "api_base" in self:
            super().__delitem__("api_base")
        elif key == "api_base" and "base_url" in self:
            super().__delitem__("base_url")

    def get(self, key: str, default: Any = None) -> Any:
        if key in self:
            return super().get(key, default)
        if key == "max_milestone_iterations" and "max_iterations" in self:
            return super().get("max_iterations", default)
        if key == "max_iterations" and "max_milestone_iterations" in self:
            return super().get("max_milestone_iterations", default)
        if key == "api_base" and "base_url" in self:
            return super().get("base_url", default)
        if key == "base_url" and "api_base" in self:
            return super().get("api_base", default)
        if key in ("max_iterations", "max_milestone_iterations"):
            return 4 if default is None else default
        if key in ("base_url", "api_base"):
            return "http://localhost:20128/v1" if default is None else default
        return super().get(key, default)

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key in self:
            return self[key]
        if key == "max_milestone_iterations" and "max_iterations" in self:
            val = self["max_iterations"]
            super().__setitem__(key, val)
            return val
        if key == "max_iterations" and "max_milestone_iterations" in self:
            val = self["max_milestone_iterations"]
            super().__setitem__(key, val)
            return val
        if key == "api_base" and "base_url" in self:
            val = self["base_url"]
            super().__setitem__(key, val)
            return val
        if key == "base_url" and "api_base" in self:
            val = self["api_base"]
            super().__setitem__(key, val)
            return val
        if default is None:
            if key in ("max_iterations", "max_milestone_iterations"):
                default = 4
            elif key in ("base_url", "api_base"):
                default = "http://localhost:20128/v1"
        val = super().setdefault(key, default)
        if key == "max_iterations":
            super().__setitem__("max_milestone_iterations", val)
        elif key == "max_milestone_iterations":
            super().__setitem__("max_iterations", val)
        elif key == "base_url":
            super().__setitem__("api_base", val)
        elif key == "api_base":
            super().__setitem__("base_url", val)
        return val


def load_config(config_path: Optional[Union[str, Path]] = None) -> ConfigDict:
    """
    Loads configuration with YAML file support and environment variable overrides.

    Precedence order:
    1. Environment variable overrides (HERMES_TEAMWORK_*, TEAMWORK_MODE)
    2. YAML configuration file (if provided and valid)
    3. Default values
    """
    defaults: Dict[str, Any] = {
        "runner": "mock",
        "model": "nous-hermes-2-yi-34b",
        "base_url": "http://localhost:20128/v1",
        "api_base": "http://localhost:20128/v1",
        "api_key": "mock-key",
        "reporting_cron": "*/8 * * * *",
        "liveness_cron": "*/10 * * * *",
        "succession_threshold": 16,
        "max_iterations": 4,
        "max_milestone_iterations": 4,
        "timeout": 120,
        "probe_dir_isolation": True,
    }

    cfg = ConfigDict(defaults)

    if config_path:
        try:
            p = Path(config_path)
            if p.is_file():
                data: Optional[Dict[str, Any]] = None
                raw_text = p.read_text(encoding="utf-8")
                try:
                    import yaml
                    loaded = yaml.safe_load(raw_text)
                    if isinstance(loaded, dict):
                        data = loaded
                except Exception:
                    try:
                        from ruamel.yaml import YAML
                        ruamel_yaml = YAML(typ="safe")
                        loaded = ruamel_yaml.load(raw_text)
                        if isinstance(loaded, dict):
                            data = loaded
                    except Exception:
                        data = None

                if data and isinstance(data, dict):
                    cfg.update(data)
                    if "max_iterations" in data:
                        cfg["max_milestone_iterations"] = data["max_iterations"]
                    if "max_milestone_iterations" in data:
                        cfg["max_iterations"] = data["max_milestone_iterations"]
                    if "base_url" in data:
                        cfg["api_base"] = data["base_url"]
                    if "api_base" in data:
                        cfg["base_url"] = data["api_base"]
        except Exception:
            pass

    # Environment variable overrides
    if "HERMES_TEAMWORK_RUNNER" in os.environ:
        cfg["runner"] = os.environ["HERMES_TEAMWORK_RUNNER"]
    elif "TEAMWORK_MODE" in os.environ and not config_path:
        cfg["runner"] = os.environ["TEAMWORK_MODE"]

    if "HERMES_TEAMWORK_MODEL" in os.environ:
        cfg["model"] = os.environ["HERMES_TEAMWORK_MODEL"]

    if "HERMES_TEAMWORK_BASE_URL" in os.environ:
        val = os.environ["HERMES_TEAMWORK_BASE_URL"]
        cfg["base_url"] = val
        cfg["api_base"] = val

    if "HERMES_TEAMWORK_API_BASE" in os.environ:
        val = os.environ["HERMES_TEAMWORK_API_BASE"]
        cfg["base_url"] = val
        cfg["api_base"] = val

    if "HERMES_TEAMWORK_API_KEY" in os.environ:
        cfg["api_key"] = os.environ["HERMES_TEAMWORK_API_KEY"]

    if "HERMES_TEAMWORK_SUCCESSION_THRESHOLD" in os.environ:
        try:
            cfg["succession_threshold"] = int(os.environ["HERMES_TEAMWORK_SUCCESSION_THRESHOLD"])
        except ValueError:
            pass

    if "HERMES_TEAMWORK_MAX_ITERATIONS" in os.environ:
        try:
            val = int(os.environ["HERMES_TEAMWORK_MAX_ITERATIONS"])
            cfg["max_iterations"] = val
            cfg["max_milestone_iterations"] = val
        except ValueError:
            pass

    if "HERMES_TEAMWORK_TIMEOUT" in os.environ:
        try:
            cfg["timeout"] = int(os.environ["HERMES_TEAMWORK_TIMEOUT"])
        except ValueError:
            pass

    return cfg
