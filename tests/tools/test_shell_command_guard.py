"""镜像 TS shell-command-guard.spec.ts 的守卫用例。"""
from tools.offense.control.shell_command_guard import (
    execute_command_shell_profile,
    shell_profile,
    validate_command_against_shell,
)


class TestShellCommandGuard:
    def test_flags_cmdlet_style_command_in_cmd_profile(self):
        profile = shell_profile("cmd", "cmd.exe")
        assert "PowerShell" in validate_command_against_shell("Get-ChildItem", profile)

    def test_allows_plain_cmd_usage(self):
        profile = shell_profile("cmd", "cmd.exe")
        assert validate_command_against_shell("dir /b", profile) is None

    def test_flags_findstr_in_posix_profile(self):
        profile = shell_profile("posix", "bash")
        assert "cmd" in validate_command_against_shell("findstr /i foo bar.txt", profile)

    def test_allows_posix_commands(self):
        profile = shell_profile("posix", "bash")
        assert validate_command_against_shell("grep -R pattern .", profile) is None

    # 补充边界（对齐 TS 实现分支）
    def test_posix_flags_percent_var(self):
        profile = shell_profile("posix", "zsh")
        assert validate_command_against_shell("echo %PATH%", profile) is not None

    def test_posix_flags_wmic(self):
        profile = shell_profile("posix", "bash")
        assert validate_command_against_shell("wmic cpu get name", profile) is not None

    def test_posix_allows_nested_cmd_prefix(self):
        profile = shell_profile("posix", "bash")
        # 以 cmd / powershell 开头的跨 shell 调用视为有意为之
        assert validate_command_against_shell("cmd /c dir", profile) is None

    def test_powershell_flags_findstr(self):
        profile = shell_profile("powershell", "pwsh")
        msg = validate_command_against_shell("findstr /i foo bar.txt", profile)
        assert msg is not None and "cmd" in msg

    def test_empty_command_passes(self):
        assert validate_command_against_shell("   ", shell_profile("posix", "bash")) is None

    def test_execute_profile_matches_platform(self):
        profile = execute_command_shell_profile()
        import sys

        if sys.platform == "win32":
            assert profile.kind == "cmd"
        else:
            assert profile.kind == "posix"
            assert "-lc" in profile.label
