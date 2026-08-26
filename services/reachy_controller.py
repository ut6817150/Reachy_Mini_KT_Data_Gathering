"""Connect to Reachy Mini and expose the robot actions used by the study."""

from collections.abc import Iterable
from pathlib import Path
from typing import Any


WIRED = "wired"
WIRELESS = "wireless"
CONNECTION_MODES = {
    "Wired / Reachy Mini Lite": WIRED,
    "Wireless Reachy Mini": WIRELESS,
}
SDK_MODES = {WIRED: "localhost_only", WIRELESS: "network"}
EMOTIONS_DATASET = "pollen-robotics/reachy-mini-emotions-library"
REACHY_PORT = 8000
CONNECTION_TIMEOUT_SECONDS = 5.0


class ReachyConnectionError(RuntimeError):
    pass


def _load_reachy_factory():
    try:
        from reachy_mini import ReachyMini
    except ImportError as error:
        raise ReachyConnectionError(
            "The reachy-mini package is not installed. Run "
            "'python -m pip install -r requirements.txt'."
        ) from error
    return ReachyMini


def _load_emotion_library():
    try:
        from reachy_mini.motion.recorded_move import RecordedMoves
    except ImportError as error:
        raise ReachyConnectionError(
            "Reachy Mini's recorded-move support is unavailable. Reinstall the "
            "requirements before using emotions."
        ) from error
    return RecordedMoves(EMOTIONS_DATASET)


class ReachyController:
    """Keep one wired or wireless Reachy connection open for the study."""

    def __init__(
        self,
        mode: str = WIRED,
        wireless_host: str = "reachy-mini.local",
    ) -> None:
        if mode not in SDK_MODES:
            raise ValueError("Unknown Reachy connection mode.")
        wireless_host = wireless_host.strip()
        if (
            not wireless_host
            or "://" in wireless_host
            or "/" in wireless_host
            or any(character.isspace() for character in wireless_host)
        ):
            raise ValueError(
                "Enter a hostname or IP address without a URL scheme or path."
            )
        self.mode = mode
        self.wireless_host = wireless_host
        self._robot: Any | None = None
        self._emotion_library: Any | None = None
        self._connection_label: str | None = None
        self._prepared_sounds: dict[Path, str] = {}
        self._speaker_volume: int | None = None

    @property
    def is_connected(self) -> bool:
        return self._robot is not None

    @property
    def robot(self):
        if self._robot is None:
            raise ReachyConnectionError(
                "Connect to Reachy Mini before starting the study."
            )
        return self._robot

    def settings(self) -> dict[str, object]:
        settings: dict[str, object] = {
            "mode": self.mode,
            "wireless_host": self.wireless_host,
        }
        if self._speaker_volume is not None:
            settings["speaker_volume"] = self._speaker_volume
        return settings

    def connect(self) -> str:
        if self._connection_label:
            return self._connection_label

        sdk_mode = SDK_MODES[self.mode]
        host = "localhost" if self.mode == WIRED else self.wireless_host
        try:
            robot = _load_reachy_factory()(
                host=host,
                port=REACHY_PORT,
                connection_mode=sdk_mode,
                spawn_daemon=False,
                use_sim=False,
                timeout=CONNECTION_TIMEOUT_SECONDS,
                media_backend="default",
            )
            enter = getattr(robot, "__enter__", None)
            if callable(enter):
                robot = enter() or robot
        except Exception as error:
            raise ReachyConnectionError(self._connection_error_message()) from error

        resolved_mode = str(getattr(robot, "connection_mode", sdk_mode))
        client = getattr(robot, "client", None)
        fallback_host = "localhost" if resolved_mode == "localhost_only" else host
        host = getattr(client, "host", fallback_host)
        port = getattr(client, "port", REACHY_PORT)
        connection_type = "Wireless" if resolved_mode == "network" else "Wired / local"

        self._robot = robot
        self._connection_label = f"{connection_type}: {host}:{port}"
        return self._connection_label

    def disconnect(self) -> None:
        robot = self._robot
        self._robot = None
        self._connection_label = None
        self._prepared_sounds.clear()
        if robot is None:
            return

        exit_method = getattr(robot, "__exit__", None)
        if callable(exit_method):
            exit_method(None, None, None)
            return
        media = getattr(robot, "media_manager", None)
        if callable(getattr(media, "close", None)):
            media.close()
        client = getattr(robot, "client", None)
        if callable(getattr(client, "disconnect", None)):
            client.disconnect()

    def prepare_sounds(self, audio_paths: Iterable[str | Path]) -> int:
        """Prepare local speech files for low-latency playback."""

        paths = [Path(path).expanduser().resolve() for path in audio_paths]
        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(f"Robot speech file does not exist: {path}")

        if self.mode == WIRED:
            self._prepared_sounds.update({path: str(path) for path in paths})
            return len(paths)

        audio_backend = getattr(self.robot.media, "audio", None)
        upload_sound = getattr(audio_backend, "upload_sound", None)
        if not callable(upload_sound):
            raise ReachyConnectionError(
                "Reachy's wireless audio backend cannot upload prepared speech."
            )

        try:
            prepared = {path: str(upload_sound(str(path))) for path in paths}
        except Exception as error:
            raise ReachyConnectionError(
                "Could not upload the prepared speech files to wireless Reachy."
            ) from error

        self._prepared_sounds.update(prepared)
        return len(paths)

    def play_sound(self, audio_path: str | Path) -> None:
        path = Path(audio_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Robot speech file does not exist: {path}")

        playback_path = self._prepared_sounds.get(path)
        if playback_path is None and self.mode == WIRELESS:
            self.prepare_sounds((path,))
            playback_path = self._prepared_sounds[path]

        self.robot.media.play_sound(playback_path or str(path))

    def stop_sound(self) -> None:
        stop_playing = getattr(self.robot.media, "stop_playing", None)
        if not callable(stop_playing):
            raise ReachyConnectionError("Reachy's audio backend cannot stop playback.")
        stop_playing()

    def set_volume(self, volume: int) -> None:
        """Set the robot's global speaker volume from 0 to 100."""

        if (
            isinstance(volume, bool)
            or not isinstance(volume, int)
            or not 0 <= volume <= 100
        ):
            raise ValueError("Reachy speaker volume must be an integer from 0 to 100.")
        try:
            from reachy_mini.io.protocol import SetVolumeCmd

            self.robot.client.send_command(SetVolumeCmd(volume=volume))
        except ReachyConnectionError:
            raise
        except Exception as error:
            raise ReachyConnectionError(
                "Reachy's speaker volume could not be set."
            ) from error
        self._speaker_volume = volume

    def wake_up(self) -> None:
        try:
            robot = self.robot
            robot.enable_motors()
            robot.wake_up()
        except ReachyConnectionError:
            raise
        except Exception as error:
            raise ReachyConnectionError("Reachy could not wake up.") from error

    def play_emotion(self, name: str) -> None:
        if not name.strip():
            raise ValueError("Emotion name cannot be empty")
        try:
            from reachy_mini.reachy_mini import (
                INIT_ANTENNAS_JOINT_POSITIONS,
                INIT_HEAD_POSE,
            )

            if self._emotion_library is None:
                self._emotion_library = _load_emotion_library()
            move = self._emotion_library.get(name.strip())
            self.robot.play_move(move, initial_goto_duration=0.5, sound=False)
            self.robot.goto_target(
                head=INIT_HEAD_POSE,
                antennas=INIT_ANTENNAS_JOINT_POSITIONS,
                body_yaw=0.0,
                duration=0.5,
            )
        except Exception as error:
            raise ReachyConnectionError(
                f"Reachy could not play the '{name.strip()}' emotion."
            ) from error

    def goto_sleep(self) -> None:
        self.robot.goto_sleep()

    def _connection_error_message(self) -> str:
        if self.mode == WIRED:
            return (
                f"Could not connect to the wired Reachy Mini daemon at "
                f"localhost:{REACHY_PORT}. "
                "Connect the robot in Reachy Mini Control and keep the control app open."
            )
        if self.mode == WIRELESS:
            return (
                f"Could not connect to the wireless Reachy Mini at "
                f"{self.wireless_host}:{REACHY_PORT}. Confirm that the robot and this "
                "computer are on the same network."
            )
        return (
            "Could not find Reachy Mini locally or on the network. Start the wired "
            "daemon in Reachy Mini Control, or confirm that the wireless robot is online."
        )
