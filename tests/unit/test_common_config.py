import pytest

from services.common.config import expand_env_placeholders, load_dotenv_if_present, load_yaml


def test_load_yaml_reads_a_file(tmp_path):
    path = tmp_path / "x.yaml"
    path.write_text("a: 1\nb: two\n")
    assert load_yaml(str(path)) == {"a": 1, "b": "two"}


def test_expand_env_placeholders_substitutes_known_vars(monkeypatch):
    monkeypatch.setenv("NVR_HOST", "10.0.0.5")
    monkeypatch.setenv("NVR_USER", "admin")
    result = expand_env_placeholders("rtsp://${NVR_USER}@${NVR_HOST}:554/stream")
    assert result == "rtsp://admin@10.0.0.5:554/stream"


def test_expand_env_placeholders_leaves_unknown_vars_untouched(monkeypatch):
    monkeypatch.delenv("NOT_SET_ANYWHERE", raising=False)
    result = expand_env_placeholders("value=${NOT_SET_ANYWHERE}")
    assert result == "value=${NOT_SET_ANYWHERE}"  # safe_substitute, not substitute - no KeyError


def test_expand_env_placeholders_noop_on_plain_text():
    assert expand_env_placeholders("no placeholders here") == "no placeholders here"


def test_load_dotenv_if_present_is_a_noop_when_file_missing(tmp_path):
    missing = tmp_path / "does_not_exist.env"
    load_dotenv_if_present(str(missing))  # must not raise


def test_load_dotenv_if_present_loads_vars(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_DOTENV_VAR", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_DOTENV_VAR=hello\n")
    load_dotenv_if_present(str(env_file))
    import os
    assert os.environ["TEST_DOTENV_VAR"] == "hello"
