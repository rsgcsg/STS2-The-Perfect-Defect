"""The documented locked CLI must load dotenv without auth or compute in tests."""
from __future__ import annotations

from click.testing import CliRunner
from modal.cli.secret import secret_cli


def test_locked_modal_dotenv_creation_keeps_values_out_of_output(tmp_path, monkeypatch) -> None:
    from modal.cli import secret

    source = tmp_path / "storage.env"
    source.write_text("AWS_ACCESS_KEY_ID=synthetic-key\nAWS_SECRET_ACCESS_KEY=synthetic-value\n")
    captured = []

    async def create(self, name, values):
        captured.append((name, values))

    monkeypatch.setattr(type(secret._Secret.objects), "create", create)

    async def forbidden_auth(*args, **kwargs):
        raise AssertionError("portable test attempted provider authentication")

    monkeypatch.setattr(secret._Client, "from_env", forbidden_auth)
    monkeypatch.setattr(secret, "ensure_env", lambda env: env)
    result = CliRunner().invoke(secret_cli, [
        "create", "stpd-worker-storage", "--env", "test", "--from-dotenv", str(source),
    ])
    assert result.exit_code == 0, type(result.exception).__name__
    assert captured == [("stpd-worker-storage", {
        "AWS_ACCESS_KEY_ID": "synthetic-key", "AWS_SECRET_ACCESS_KEY": "synthetic-value",
    })]
    assert "synthetic-key" not in result.output
    assert "synthetic-value" not in result.output
