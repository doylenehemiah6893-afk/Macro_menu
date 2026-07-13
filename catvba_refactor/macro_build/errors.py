from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    CONFIG = 2
    SOURCE = 3
    INFRASTRUCTURE = 4
    VERIFICATION = 5


class BuildKitError(Exception):
    exit_code = ExitCode.INFRASTRUCTURE


class ConfigError(BuildKitError):
    exit_code = ExitCode.CONFIG


class SourceError(BuildKitError):
    exit_code = ExitCode.SOURCE


class InfrastructureError(BuildKitError):
    exit_code = ExitCode.INFRASTRUCTURE


class VerificationError(BuildKitError):
    exit_code = ExitCode.VERIFICATION
