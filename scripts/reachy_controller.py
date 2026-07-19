"""Connection lifecycle for wired and wireless Reachy Mini robots.

Reachy Mini uses the same Python SDK for both hardware variants. A wired/Lite
robot is reached through the daemon on this computer (``localhost:8000``),
while a wireless robot is reached through the daemon running on the robot
(``reachy-mini.local:8000`` by default).

This module deliberately passes ``spawn_daemon=False`` in every mode. Reachy
Mini Control owns the wired daemon, and the wireless daemon already runs on the
robot. Starting another daemon from Streamlit could compete for the hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Mapping


class RobotConnectionMode(str, Enum):
    """Connection choices displayed on the study start page."""

    AUTO = "auto"
    WIRED = "wired"
    WIRELESS = "wireless"

    @property
    def label(self) -> str:
        labels = {
            RobotConnectionMode.AUTO: "Automatic (wired first, then wireless)",
            RobotConnectionMode.WIRED: "Wired / Reachy Mini Lite",
            RobotConnectionMode.WIRELESS: "Wireless Reachy Mini",
        }
        return labels[self]


CONNECTION_MODE_OPTIONS: tuple[RobotConnectionMode, ...] = tuple(RobotConnectionMode)


@dataclass(frozen=True, slots=True)
class ReachyConnectionConfig:
    """Validated settings used to create a Reachy Mini SDK client."""

    mode: RobotConnectionMode = RobotConnectionMode.AUTO
    wireless_host: str = "reachy-mini.local"
    port: int = 8000
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        mode = self.mode
        if isinstance(mode, str):
            try:
                mode = RobotConnectionMode(mode.lower())
            except ValueError as error:
                choices = ", ".join(item.value for item in RobotConnectionMode)
                raise ValueError(f"mode must be one of: {choices}") from error
            object.__setattr__(self, "mode", mode)

        host = self.wireless_host.strip()
        if not host:
            raise ValueError("wireless_host cannot be empty")
        if "://" in host or "/" in host or any(character.isspace() for character in host):
            raise ValueError(
                "wireless_host must be a hostname or IP address without a URL scheme or path"
            )
        object.__setattr__(self, "wireless_host", host)

        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

    @property
    def sdk_connection_mode(self) -> str:
        """Translate the UI mode into the SDK's connection-mode vocabulary."""

        return {
            RobotConnectionMode.AUTO: "auto",
            RobotConnectionMode.WIRED: "localhost_only",
            RobotConnectionMode.WIRELESS: "network",
        }[self.mode]

    def sdk_kwargs(self) -> dict[str, Any]:
        """Build safe SDK arguments shared by all call sites."""

        return {
            "host": self.wireless_host,
            "port": self.port,
            "connection_mode": self.sdk_connection_mode,
            "spawn_daemon": False,
            "use_sim": False,
            "timeout": self.timeout_seconds,
            # Auto-select LOCAL media for a local daemon and WebRTC for a
            # wireless daemon. This keeps robot speech portable.
            "media_backend": "default",
        }


@dataclass(frozen=True, slots=True)
class ReachyConnectionInfo:
    """The actual connection selected by the SDK."""

    requested_mode: RobotConnectionMode
    resolved_mode: str
    host: str
    port: int

    @property
    def is_wireless(self) -> bool:
        return self.resolved_mode == "network"

    @property
    def label(self) -> str:
        connection_type = "Wireless" if self.is_wireless else "Wired / local"
        return f"{connection_type}: {self.host}:{self.port}"


class ReachyConnectionError(RuntimeError):
    """Raised when the study app cannot establish a Reachy connection."""


class ReachyNotConnectedError(RuntimeError):
    """Raised when robot behavior is requested before connecting."""


ReachyFactory = Callable[..., Any]
EmotionLibraryFactory = Callable[[], Any]
EMOTIONS_DATASET = "pollen-robotics/reachy-mini-emotions-library"


def _load_reachy_factory() -> ReachyFactory:
    """Import the optional SDK only when a connection is requested."""

    try:
        from reachy_mini import ReachyMini
    except ImportError as error:
        raise ReachyConnectionError(
            "The reachy-mini package is not installed. Run "
            "'python -m pip install -r requirements.txt'."
        ) from error
    return ReachyMini


def _load_emotion_library() -> Any:
    """Load the official emotion library only when an emotion is requested."""

    try:
        from reachy_mini.motion.recorded_move import RecordedMoves
    except ImportError as error:
        raise ReachyConnectionError(
            "Reachy Mini's recorded-move support is unavailable. Reinstall the "
            "requirements before using emotions."
        ) from error
    return RecordedMoves(EMOTIONS_DATASET)


class ReachyController:
    """Own exactly one SDK client and release it deterministically."""

    def __init__(
        self,
        config: ReachyConnectionConfig | None = None,
        *,
        factory: ReachyFactory | None = None,
        emotion_library_factory: EmotionLibraryFactory | None = None,
    ) -> None:
        self.config = config or ReachyConnectionConfig()
        self._factory = factory
        self._emotion_library_factory = emotion_library_factory
        self._emotion_library: Any | None = None
        self._robot: Any | None = None
        self._connection_info: ReachyConnectionInfo | None = None

    @property
    def is_connected(self) -> bool:
        return self._robot is not None

    @property
    def connection_info(self) -> ReachyConnectionInfo | None:
        return self._connection_info

    @property
    def robot(self) -> Any:
        """Return the SDK client or fail with a user-actionable error."""

        if self._robot is None:
            raise ReachyNotConnectedError("Connect to Reachy Mini before starting the study.")
        return self._robot

    def connect(self) -> ReachyConnectionInfo:
        """Connect using the selected mode and report the SDK's resolved route."""

        if self._robot is not None and self._connection_info is not None:
            return self._connection_info

        factory = self._factory or _load_reachy_factory()
        try:
            robot = factory(**self.config.sdk_kwargs())
            # ReachyMini.__enter__ currently returns itself. Calling it keeps
            # this wrapper correctly paired with the public context-manager API.
            enter = getattr(robot, "__enter__", None)
            if callable(enter):
                entered_robot = enter()
                if entered_robot is not None:
                    robot = entered_robot
        except Exception as error:
            raise ReachyConnectionError(self._connection_error_message()) from error

        client = getattr(robot, "client", None)
        resolved_mode = str(
            getattr(robot, "connection_mode", self.config.sdk_connection_mode)
        )
        host = str(getattr(client, "host", self._fallback_host(resolved_mode)))
        port = int(getattr(client, "port", self.config.port))

        self._robot = robot
        self._connection_info = ReachyConnectionInfo(
            requested_mode=self.config.mode,
            resolved_mode=resolved_mode,
            host=host,
            port=port,
        )
        return self._connection_info

    def disconnect(self) -> None:
        """Close robot media and its daemon client without stopping the daemon."""

        robot = self._robot
        self._robot = None
        self._connection_info = None
        if robot is None:
            return

        exit_method = getattr(robot, "__exit__", None)
        if callable(exit_method):
            exit_method(None, None, None)
            return

        # Defensive fallback for test doubles or future SDK variants.
        media = getattr(robot, "media_manager", None)
        if media is not None and callable(getattr(media, "close", None)):
            media.close()
        client = getattr(robot, "client", None)
        if client is not None and callable(getattr(client, "disconnect", None)):
            client.disconnect()

    def play_sound(self, audio_path: str | Path) -> None:
        """Play a generated question or acknowledgement through Reachy's speaker."""

        path = Path(audio_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Robot speech file does not exist: {path}")
        self.robot.media.play_sound(str(path))

    def stop_sound(self) -> None:
        """Stop the audio currently playing through Reachy."""

        media = self.robot.media
        stop_playing = getattr(media, "stop_playing", None)
        if not callable(stop_playing):
            raise ReachyConnectionError("Reachy's audio backend cannot stop playback.")
        stop_playing()

    def wake_up(self) -> None:
        """Wake Reachy before beginning a participant session."""

        self.robot.wake_up()

    def play_emotion(self, emotion_name: str) -> None:
        """Play one move from Pollen Robotics' official emotion library."""

        normalized_name = emotion_name.strip()
        if not normalized_name:
            raise ValueError("emotion_name cannot be empty")

        robot = self.robot
        try:
            if self._emotion_library is None:
                factory = self._emotion_library_factory or _load_emotion_library
                self._emotion_library = factory()
            move = self._emotion_library.get(normalized_name)
            # The official emotion recordings can include a sidecar sound file.
            # The study only uses their motor trajectories; question and response
            # speech is handled separately by RobotSpeaker.
            robot.play_move(move, initial_goto_duration=0.5, sound=False)
        except Exception as error:
            raise ReachyConnectionError(
                f"Reachy could not play the '{normalized_name}' emotion."
            ) from error

    def goto_sleep(self) -> None:
        """Put Reachy to sleep after the session if the study enables it."""

        self.robot.goto_sleep()

    def _fallback_host(self, resolved_mode: str) -> str:
        return "localhost" if resolved_mode == "localhost_only" else self.config.wireless_host

    def _connection_error_message(self) -> str:
        if self.config.mode is RobotConnectionMode.WIRED:
            return (
                "Could not connect to the wired Reachy Mini daemon at localhost:"
                f"{self.config.port}. Connect the robot in Reachy Mini Control and keep "
                "the control app open."
            )
        if self.config.mode is RobotConnectionMode.WIRELESS:
            return (
                f"Could not connect to the wireless Reachy Mini at "
                f"{self.config.wireless_host}:{self.config.port}. Confirm that the robot "
                "and this computer are on the same network."
            )
        return (
            "Could not find Reachy Mini locally or on the network. Start the wired "
            "daemon in Reachy Mini Control, or confirm that the wireless robot is online."
        )

    def __enter__(self) -> "ReachyController":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.disconnect()


def connection_mode_labels() -> Mapping[str, RobotConnectionMode]:
    """Return stable labels suitable for a Streamlit selectbox."""

    return {mode.label: mode for mode in CONNECTION_MODE_OPTIONS}
