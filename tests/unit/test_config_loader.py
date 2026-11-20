"""
tests.unit.test_config_loader
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for ConfigDict and load_config.
"""
from __future__ import annotations

from pathlib import Path
import pytest

from hermes_teamwork.config import ConfigDict, load_config


class TestConfigDict:
    """Tests for ConfigDict dual attribute/item access and bidirectional iteration aliases."""

    def test_item_and_attribute_access(self):
        cfg = ConfigDict({"runner": "mock", "timeout": 60})
        assert cfg["runner"] == "mock"
        assert cfg.runner == "mock"
        assert cfg["timeout"] == 60
        assert cfg.timeout == 60

    def test_attribute_setting(self):
        cfg = ConfigDict({"runner": "mock"})
        cfg.runner = "openai"
        assert cfg["runner"] == "openai"
        assert cfg.runner == "openai"

    def test_item_setting(self):
        cfg = ConfigDict({"runner": "mock"})
        cfg["runner"] = "native"
        assert cfg["runner"] == "native"
        assert cfg.runner == "native"

    def test_attribute_deletion(self):
        cfg = ConfigDict({"custom": "value"})
        assert cfg.custom == "value"
        del cfg.custom
        assert "custom" not in cfg
        with pytest.raises(AttributeError):
            _ = cfg.custom

    def test_del_non_existent_attribute_raises(self):
        cfg = ConfigDict()
        with pytest.raises(AttributeError):
            del cfg.non_existent

    def test_missing_attribute_raises(self):
        cfg = ConfigDict({"foo": "bar"})
        with pytest.raises(AttributeError):
            _ = cfg.missing_key

    def test_bidirectional_iteration_alias_defaults(self):
        cfg = ConfigDict()
        assert cfg.max_iterations == 4
        assert cfg.max_milestone_iterations == 4
        assert cfg["max_iterations"] == 4
        assert cfg["max_milestone_iterations"] == 4

    def test_bidirectional_iteration_alias_sync_on_attr_set(self):
        cfg = ConfigDict({"max_iterations": 4})
        cfg.max_iterations = 8
        assert cfg.max_iterations == 8
        assert cfg.max_milestone_iterations == 8
        assert cfg["max_iterations"] == 8
        assert cfg["max_milestone_iterations"] == 8

        cfg.max_milestone_iterations = 12
        assert cfg.max_iterations == 12
        assert cfg.max_milestone_iterations == 12

    def test_bidirectional_iteration_alias_sync_on_item_set(self):
        cfg = ConfigDict({"max_iterations": 4})
        cfg["max_iterations"] = 10
        assert cfg.max_iterations == 10
        assert cfg.max_milestone_iterations == 10

        cfg["max_milestone_iterations"] = 6
        assert cfg.max_iterations == 6
        assert cfg.max_milestone_iterations == 6

    def test_bidirectional_iteration_alias_sync_on_update_dict(self):
        cfg = ConfigDict({"max_iterations": 4, "max_milestone_iterations": 4})
        cfg.update({"max_iterations": 10})
        assert cfg.max_iterations == 10
        assert cfg.max_milestone_iterations == 10
        assert cfg["max_iterations"] == 10
        assert cfg["max_milestone_iterations"] == 10

        cfg.update({"max_milestone_iterations": 8})
        assert cfg.max_iterations == 8
        assert cfg.max_milestone_iterations == 8
        assert cfg["max_iterations"] == 8
        assert cfg["max_milestone_iterations"] == 8

    def test_bidirectional_iteration_alias_sync_on_update_kwargs_and_init(self):
        cfg = ConfigDict({"max_iterations": 4})
        cfg.update(max_iterations=14)
        assert cfg.max_iterations == 14
        assert cfg.max_milestone_iterations == 14

        cfg.update(max_milestone_iterations=9)
        assert cfg.max_iterations == 9
        assert cfg.max_milestone_iterations == 9

        cfg2 = ConfigDict({"max_iterations": 12})
        assert cfg2.max_iterations == 12
        assert cfg2.max_milestone_iterations == 12

    def test_get_method_with_alias_fallback(self):
        cfg = ConfigDict({"max_iterations": 7})
        assert cfg.get("max_iterations") == 7
        assert cfg.get("max_milestone_iterations") == 7
        assert cfg.get("non_existent", "fallback") == "fallback"

    def test_bidirectional_url_alias_defaults(self):
        cfg = ConfigDict()
        assert cfg.base_url == "http://localhost:20128/v1"
        assert cfg.api_base == "http://localhost:20128/v1"
        assert cfg["base_url"] == "http://localhost:20128/v1"
        assert cfg["api_base"] == "http://localhost:20128/v1"
        assert cfg.get("base_url") == "http://localhost:20128/v1"
        assert cfg.get("api_base") == "http://localhost:20128/v1"

    def test_bidirectional_url_alias_sync_on_attr_set(self):
        cfg = ConfigDict()
        cfg.base_url = "http://remote:1234/v1"
        assert cfg.base_url == "http://remote:1234/v1"
        assert cfg.api_base == "http://remote:1234/v1"
        assert cfg["base_url"] == "http://remote:1234/v1"
        assert cfg["api_base"] == "http://remote:1234/v1"

        cfg.api_base = "http://another:5678/v1"
        assert cfg.base_url == "http://another:5678/v1"
        assert cfg.api_base == "http://another:5678/v1"

    def test_bidirectional_url_alias_sync_on_item_set(self):
        cfg = ConfigDict()
        cfg["base_url"] = "http://item-base:1111/v1"
        assert cfg.base_url == "http://item-base:1111/v1"
        assert cfg.api_base == "http://item-base:1111/v1"

        cfg["api_base"] = "http://item-api:2222/v1"
        assert cfg.base_url == "http://item-api:2222/v1"
        assert cfg.api_base == "http://item-api:2222/v1"

    def test_bidirectional_url_alias_sync_on_update(self):
        cfg = ConfigDict()
        cfg.update({"base_url": "http://updated-base:3333/v1"})
        assert cfg.base_url == "http://updated-base:3333/v1"
        assert cfg.api_base == "http://updated-base:3333/v1"

        cfg.update(api_base="http://updated-api:4444/v1")
        assert cfg.base_url == "http://updated-api:4444/v1"
        assert cfg.api_base == "http://updated-api:4444/v1"

    def test_bidirectional_url_alias_sync_on_setdefault(self):
        cfg = ConfigDict()
        val = cfg.setdefault("api_base", "http://default-api:5555/v1")
        assert val == "http://default-api:5555/v1"
        assert cfg.api_base == "http://default-api:5555/v1"
        assert cfg.base_url == "http://default-api:5555/v1"

        cfg2 = ConfigDict({"base_url": "http://existing:6666/v1"})
        val2 = cfg2.setdefault("api_base", "http://ignored:7777/v1")
        assert val2 == "http://existing:6666/v1"
        assert cfg2.api_base == "http://existing:6666/v1"
        assert cfg2.base_url == "http://existing:6666/v1"

    def test_bidirectional_url_alias_deletion(self):
        cfg = ConfigDict({"base_url": "http://test:8888/v1"})
        del cfg.base_url
        assert "base_url" not in cfg
        assert "api_base" not in cfg


class TestLoadConfig:
    """Tests for load_config function with defaults, YAML loading, and environment variable overrides."""

    def test_load_config_defaults(self):
        cfg = load_config()
        assert cfg.runner == "mock"
        assert cfg.model == "nous-hermes-2-yi-34b"
        assert cfg.base_url == "http://localhost:20128/v1"
        assert cfg.api_base == "http://localhost:20128/v1"
        assert cfg.api_key == "mock-key"
        assert cfg.reporting_cron == "*/8 * * * *"
        assert cfg.liveness_cron == "*/10 * * * *"
        assert cfg.succession_threshold == 16
        assert cfg.max_iterations == 4
        assert cfg.max_milestone_iterations == 4
        assert cfg.timeout == 120
        assert cfg.probe_dir_isolation is True

    def test_load_config_from_valid_yaml(self, tmp_path: Path):
        yaml_path = tmp_path / "teamwork_config.yaml"
        yaml_content = (
            "runner: 9router\n"
            "model: hermes-3-llama-3.1-8b\n"
            "max_iterations: 6\n"
            "timeout: 90\n"
        )
        yaml_path.write_text(yaml_content, encoding="utf-8")

        cfg = load_config(yaml_path)
        assert cfg.runner == "9router"
        assert cfg.model == "hermes-3-llama-3.1-8b"
        assert cfg.max_iterations == 6
        assert cfg.max_milestone_iterations == 6
        assert cfg.timeout == 90
        # Untouched defaults preserved
        assert cfg.succession_threshold == 16

    def test_load_config_non_existent_file_graceful(self, tmp_path: Path):
        ghost_path = tmp_path / "non_existent.yaml"
        cfg = load_config(ghost_path)
        assert cfg.runner == "mock"
        assert cfg.succession_threshold == 16

    def test_load_config_corrupted_yaml_graceful(self, tmp_path: Path):
        corrupt_path = tmp_path / "corrupt.yaml"
        corrupt_path.write_text("invalid: yaml: : : [unclosed", encoding="utf-8")
        cfg = load_config(corrupt_path)
        assert cfg.runner == "mock"
        assert cfg.succession_threshold == 16

    def test_load_config_directory_path_graceful(self, tmp_path: Path):
        cfg = load_config(tmp_path)
        assert cfg.runner == "mock"
        assert cfg.max_iterations == 4
        assert cfg.max_milestone_iterations == 4

    def test_load_config_binary_file_graceful(self, tmp_path: Path):
        bin_path = tmp_path / "binary.bin"
        bin_path.write_bytes(b"\x80\x81\x82\xff\xfe\xfd")
        cfg = load_config(bin_path)
        assert cfg.runner == "mock"
        assert cfg.max_iterations == 4
        assert cfg.max_milestone_iterations == 4

    def test_load_config_permission_error_graceful(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        unreadable_file = tmp_path / "unreadable.yaml"
        unreadable_file.write_text("runner: 9router\n", encoding="utf-8")
        
        # Monkeypatch Path.read_text to raise PermissionError
        original_read_text = Path.read_text
        def mock_read_text(self, *args, **kwargs):
            if self.name == "unreadable.yaml":
                raise PermissionError(13, "Permission denied")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", mock_read_text)
        cfg = load_config(unreadable_file)
        assert cfg.runner == "mock"
        assert cfg.max_iterations == 4
        assert cfg.max_milestone_iterations == 4

    def test_env_var_runner_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_TEAMWORK_RUNNER", "openai_custom")
        cfg = load_config()
        assert cfg.runner == "openai_custom"

    def test_env_var_teamwork_mode_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("TEAMWORK_MODE", "mode_test")
        cfg = load_config()
        assert cfg.runner == "mode_test"

    def test_runner_precedence_over_teamwork_mode(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_TEAMWORK_RUNNER", "high_pri")
        monkeypatch.setenv("TEAMWORK_MODE", "low_pri")
        cfg = load_config()
        assert cfg.runner == "high_pri"

    def test_teamwork_mode_ignored_when_config_path_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("TEAMWORK_MODE", "mode_ignored")
        yaml_file = tmp_path / "cfg.yaml"
        yaml_file.write_text("runner: native\n", encoding="utf-8")
        cfg = load_config(yaml_file)
        assert cfg.runner == "native"

    def test_env_var_model_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_TEAMWORK_MODEL", "custom-model-70b")
        cfg = load_config()
        assert cfg.model == "custom-model-70b"

    def test_env_var_base_url_and_api_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_TEAMWORK_BASE_URL", "http://127.0.0.1:9000/v1")
        monkeypatch.setenv("HERMES_TEAMWORK_API_KEY", "secret-token")
        cfg = load_config()
        assert cfg.base_url == "http://127.0.0.1:9000/v1"
        assert cfg.api_base == "http://127.0.0.1:9000/v1"
        assert cfg.api_key == "secret-token"

    def test_env_var_api_base_sync(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_TEAMWORK_API_BASE", "http://127.0.0.1:9001/v1")
        cfg = load_config()
        assert cfg.base_url == "http://127.0.0.1:9001/v1"
        assert cfg.api_base == "http://127.0.0.1:9001/v1"

    def test_load_config_yaml_api_base_synchronization(self, tmp_path: Path):
        yaml_path = tmp_path / "test_api_base.yaml"
        yaml_path.write_text("runner: 9router\napi_base: http://remote-llm:8000/v1\n", encoding="utf-8")
        cfg = load_config(yaml_path)
        assert cfg.api_base == "http://remote-llm:8000/v1"
        assert cfg.base_url == "http://remote-llm:8000/v1"
        assert cfg.get("api_base") == "http://remote-llm:8000/v1"
        assert cfg.get("base_url") == "http://remote-llm:8000/v1"

    def test_env_var_succession_threshold_valid_and_invalid(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_TEAMWORK_SUCCESSION_THRESHOLD", "24")
        cfg = load_config()
        assert cfg.succession_threshold == 24

        monkeypatch.setenv("HERMES_TEAMWORK_SUCCESSION_THRESHOLD", "not-a-number")
        cfg2 = load_config()
        assert cfg2.succession_threshold == 16

    def test_env_var_max_iterations_valid_and_invalid(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_TEAMWORK_MAX_ITERATIONS", "9")
        cfg = load_config()
        assert cfg.max_iterations == 9
        assert cfg.max_milestone_iterations == 9

        monkeypatch.setenv("HERMES_TEAMWORK_MAX_ITERATIONS", "bad-number")
        cfg2 = load_config()
        assert cfg2.max_iterations == 4
        assert cfg2.max_milestone_iterations == 4

    def test_env_var_timeout_valid_and_invalid(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HERMES_TEAMWORK_TIMEOUT", "300")
        cfg = load_config()
        assert cfg.timeout == 300

        monkeypatch.setenv("HERMES_TEAMWORK_TIMEOUT", "invalid-int")
        cfg2 = load_config()
        assert cfg2.timeout == 120
