"""Hardware-independent checks for Reachy connectivity and actions."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.reachy_controller import (
    CONNECTION_MODES,
    WIRED,
    WIRELESS,
    ReachyConnectionError,
    ReachyController,
)


class FakeMedia:
    def __init__(self) -> None:
        self.played: list[str] = []
        self.uploaded: list[str] = []
        self.stopped = False
        self.audio = self

    def upload_sound(self, path: str) -> str:
        self.uploaded.append(path)
        return f"/tmp/reachy_mini_sounds/{Path(path).name}"

    def play_sound(self, path: str) -> None:
        self.played.append(path)

    def stop_playing(self) -> None:
        self.stopped = True


class FakeClient:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.sent_commands: list[object] = []

    def send_command(self, command: object) -> None:
        self.sent_commands.append(command)


class FakeRobot:
    def __init__(self, mode: str, host: str, port: int) -> None:
        self.connection_mode = mode
        self.client = FakeClient(host, port)
        self.media = FakeMedia()
        self.exited = False
        self.woke_up = False
        self.motors_enabled = False
        self.went_to_sleep = False
        self.played_moves: list[tuple[object, float, bool]] = []
        self.goto_targets: list[dict[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        self.exited = True

    def wake_up(self) -> None:
        self.woke_up = True

    def enable_motors(self) -> None:
        self.motors_enabled = True

    def goto_sleep(self) -> None:
        self.went_to_sleep = True

    def play_move(self, move, *, initial_goto_duration: float, sound: bool) -> None:
        self.played_moves.append((move, initial_goto_duration, sound))

    def goto_target(self, **target: object) -> None:
        self.goto_targets.append(target)


class Factory:
    def __init__(self, resolved_mode: str, host: str) -> None:
        self.resolved_mode = resolved_mode
        self.host = host
        self.calls: list[dict[str, object]] = []
        self.robot: FakeRobot | None = None

    def __call__(self, **settings: object) -> FakeRobot:
        self.calls.append(settings)
        self.robot = FakeRobot(self.resolved_mode, self.host, int(settings["port"]))
        return self.robot


class ReachyControllerTests(unittest.TestCase):
    def connect(self, controller: ReachyController, factory: Factory) -> str:
        with patch(
            "services.reachy_controller._load_reachy_factory", return_value=factory
        ):
            return controller.connect()

    def test_connection_options_are_plain_strings(self) -> None:
        self.assertEqual(set(CONNECTION_MODES.values()), {WIRED, WIRELESS})
        controller = ReachyController(WIRELESS, " 192.168.1.8 ")
        self.assertEqual(controller.mode, WIRELESS)
        self.assertEqual(controller.wireless_host, "192.168.1.8")

    def test_wired_is_the_default_mode(self) -> None:
        self.assertEqual(ReachyController().mode, WIRED)

    def test_rejects_invalid_host(self) -> None:
        with self.assertRaises(ValueError):
            ReachyController(wireless_host="http://reachy-mini.local")

    def test_wired_connection_uses_local_daemon(self) -> None:
        factory = Factory("localhost_only", "localhost")
        controller = ReachyController(WIRED)
        label = self.connect(controller, factory)
        self.assertEqual(factory.calls[0]["connection_mode"], "localhost_only")
        self.assertEqual(factory.calls[0]["host"], "localhost")
        self.assertEqual(factory.calls[0]["port"], 8000)
        self.assertEqual(factory.calls[0]["timeout"], 5.0)
        self.assertIs(factory.calls[0]["spawn_daemon"], False)
        self.assertEqual(label, "Wired / local: localhost:8000")

    def test_wireless_connection_uses_configured_host(self) -> None:
        factory = Factory("network", "192.168.1.42")
        controller = ReachyController(WIRELESS, "192.168.1.42")
        label = self.connect(controller, factory)
        self.assertEqual(factory.calls[0]["connection_mode"], "network")
        self.assertEqual(factory.calls[0]["host"], "192.168.1.42")
        self.assertEqual(label, "Wireless: 192.168.1.42:8000")

    def test_disconnect_closes_the_sdk_context(self) -> None:
        factory = Factory("localhost_only", "localhost")
        controller = ReachyController()
        self.connect(controller, factory)
        controller.disconnect()
        self.assertIsNotNone(factory.robot)
        self.assertTrue(factory.robot.exited)  # type: ignore[union-attr]
        self.assertFalse(controller.is_connected)

    def test_actions_require_a_connection(self) -> None:
        with self.assertRaises(ReachyConnectionError):
            ReachyController().wake_up()

    def test_speaker_volume_uses_existing_robot_connection(self) -> None:
        factory = Factory("network", "192.168.1.42")
        controller = ReachyController(WIRELESS, "192.168.1.42")
        self.connect(controller, factory)

        controller.set_volume(65)

        robot = factory.robot
        self.assertIsNotNone(robot)
        command = robot.client.sent_commands[-1]  # type: ignore[union-attr]
        self.assertEqual(command.volume, 65)  # type: ignore[attr-defined]
        self.assertEqual(controller.settings()["speaker_volume"], 65)

    def test_speaker_volume_rejects_values_outside_zero_to_one_hundred(self) -> None:
        controller = ReachyController()
        for volume in (-1, 101):
            with self.subTest(volume=volume), self.assertRaises(ValueError):
                controller.set_volume(volume)

    def test_sound_emotion_wake_and_sleep(self) -> None:
        factory = Factory("localhost_only", "localhost")
        controller = ReachyController()
        self.connect(controller, factory)
        emotions = type(
            "Emotions", (), {"get": lambda _self, name: {"emotion": name}}
        )()

        with tempfile.TemporaryDirectory() as temp_dir:
            sound = Path(temp_dir) / "speech.wav"
            sound.touch()
            controller.play_sound(sound)
            controller.stop_sound()
        with patch(
            "services.reachy_controller._load_emotion_library",
            return_value=emotions,
        ):
            controller.wake_up()
            controller.play_emotion("welcoming1")
            controller.goto_sleep()

        robot = factory.robot
        self.assertIsNotNone(robot)
        self.assertTrue(robot.woke_up)  # type: ignore[union-attr]
        self.assertTrue(robot.motors_enabled)  # type: ignore[union-attr]
        self.assertTrue(robot.went_to_sleep)  # type: ignore[union-attr]
        self.assertTrue(robot.media.stopped)  # type: ignore[union-attr]
        self.assertEqual(robot.played_moves[-1][2], False)  # type: ignore[union-attr]
        neutral = robot.goto_targets[-1]  # type: ignore[union-attr]
        self.assertEqual(neutral["body_yaw"], 0.0)
        self.assertEqual(neutral["duration"], 0.5)
        self.assertIn("head", neutral)
        self.assertIn("antennas", neutral)

    def test_wired_preparation_keeps_local_sound_path(self) -> None:
        factory = Factory("localhost_only", "localhost")
        controller = ReachyController(WIRED)
        self.connect(controller, factory)

        with tempfile.TemporaryDirectory() as temp_dir:
            sound = Path(temp_dir) / "speech.wav"
            sound.touch()
            self.assertEqual(controller.prepare_sounds((sound,)), 1)
            controller.play_sound(sound)

        robot = factory.robot
        self.assertIsNotNone(robot)
        self.assertEqual(robot.media.uploaded, [])  # type: ignore[union-attr]
        self.assertEqual(robot.media.played, [str(sound.resolve())])  # type: ignore[union-attr]

    def test_wireless_preparation_uploads_once_and_reuses_remote_path(self) -> None:
        factory = Factory("network", "192.168.1.42")
        controller = ReachyController(WIRELESS, "192.168.1.42")
        self.connect(controller, factory)

        with tempfile.TemporaryDirectory() as temp_dir:
            sound = Path(temp_dir) / "speech.wav"
            sound.touch()
            local_path = str(sound.resolve())
            remote_path = "/tmp/reachy_mini_sounds/speech.wav"

            self.assertEqual(controller.prepare_sounds((sound,)), 1)
            controller.play_sound(sound)
            controller.play_sound(sound)

        robot = factory.robot
        self.assertIsNotNone(robot)
        self.assertEqual(robot.media.uploaded, [local_path])  # type: ignore[union-attr]
        self.assertEqual(  # type: ignore[union-attr]
            robot.media.played,
            [remote_path, remote_path],
        )

    def test_connection_failure_has_useful_message(self) -> None:
        def fail(**_settings: object):
            raise ConnectionError("offline")

        with patch(
            "services.reachy_controller._load_reachy_factory", return_value=fail
        ):
            with self.assertRaisesRegex(ReachyConnectionError, "wireless Reachy Mini"):
                ReachyController(WIRELESS).connect()


if __name__ == "__main__":
    unittest.main()
