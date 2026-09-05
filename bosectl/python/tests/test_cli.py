"""Tests for user-visible CLI output."""

import stat
import sys

from pybmap.cli import _git_hash, cmd_status
from pybmap.types import BatteryReading, DeviceStatus


class StatusDevice:
    device_info = {"name": "Bose QuietComfort Ultra Earbuds (2nd Gen)"}
    battery_components = {1: "Right", 2: "Left", 3: "Case"}

    def status(self):
        return DeviceStatus(
            battery=70,
            battery_readings=[
                BatteryReading(3, 80),
                BatteryReading(4, 70),
                BatteryReading(2, 60),
                BatteryReading(1, 50),
            ],
            mode="quiet",
            mode_idx=0,
            cnc_level=0,
            cnc_max=10,
            eq=[],
            name="edith",
            firmware="1.0.0",
            sidetone="off",
            multipoint=False,
            auto_pause=True,
            auto_answer=False,
            prompts_enabled=False,
            prompts_language="US English",
        )

    def has_feature(self, _name):
        return False


def test_status_orders_known_components_and_hides_combined(capsys):
    cmd_status(StatusDevice())
    output = capsys.readouterr().out

    assert output.index("Right") < output.index("Left") < output.index("Case")
    assert "Right        50%" in output
    assert "Left         60%" in output
    assert "Case         80%" in output
    assert "Combined" not in output


def test_device_status_preserves_old_positional_shape():
    status = DeviceStatus(
        80, "quiet", 0, 7, 10, [], "Device", "1.0.0", "off",
        False, True, False, True, "English",
    )
    assert status.mode == "quiet"
    assert status.battery_readings == ()


def test_git_hash_falls_back_on_gushing_git(tmp_path, monkeypatch):
    stub = tmp_path / "git"
    stub.write_text(
        "#!%s\nimport sys; sys.stdout.write('g' * 1000000)\n" % sys.executable
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert _git_hash() == "unknown"
