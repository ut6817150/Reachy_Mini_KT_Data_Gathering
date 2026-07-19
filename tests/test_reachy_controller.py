"""Hardware-independent tests for wired and wireless Reachy connectivity."""

from pathlib import Path
import tempfile
import unittest

from scripts.reachy_controller import (
    ReachyConnectionConfig,
    ReachyConnectionError,
    ReachyController,
    ReachyNotConnectedError,
    RobotConnectionMode,
    connection_mode_labels,
)


class FakeClient:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port


class FakeMedia:
    def __init__(self) -> None:
        self.played: list[str] = []
        self.stopped = False

    def play_sound(self, path: str) -> None:
        self.played.append(path)

    def stop_playing(self) -> None:
        self.stopped = True


class FakeRobot:
    def __init__(self, *, resolved_mode: str, host: str, port: int) -> None:
        self.connection_mode = resolved_mode
        self.client = FakeClient(host, port)
        self.media = FakeMedia()
        self.entered = False
        self.exited = False
        self.woke_up = False
        self.went_to_sleep = False
        self.played_moves: list[tuple[object, float, bool]] = []

    def __enter__(self) -> "FakeRobot":
        self.entered = True
        return self

    def __exit__(self, *_args: object) -> None:
        self.exited = True

    def wake_up(self) -> None:
        self.woke_up = True

    def goto_sleep(self) -> None:
        self.went_to_sleep = True

    def play_move(
        self,
        move: object,
        *,
        initial_goto_duration: float,
        sound: bool = True,
    ) -> None:
        self.played_moves.append((move, initial_goto_duration, sound))


class FakeEmotionLibrary:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def get(self, name: str) -> object:
        self.requested.append(name)
        return {"emotion": name}


class CapturingFactory:
    def __init__(self, resolved_mode: str, host: str) -> None:
        self.resolved_mode = resolved_mode
        self.host = host
        self.calls: list[dict[str, object]] = []
        self.robot: FakeRobot | None = None

    def __call__(self, **kwargs: object) -> FakeRobot:
        self.calls.append(kwargs)
        self.robot = FakeRobot(
            resolved_mode=self.resolved_mode,
            host=self.host,
            port=int(kwargs["port"]),
        )
        return self.robot


class ConnectionConfigTests(unittest.TestCase):
    def test_maps_modes_to_sdk_values(self) -> None:
        self.assertEqual(
            ReachyConnectionConfig(mode=RobotConnectionMode.AUTO).sdk_connection_mode,
            "auto",
        )
        self.assertEqual(
            ReachyConnectionConfig(mode=RobotConnectionMode.WIRED).sdk_connection_mode,
            "localhost_only",
        )
        self.assertEqual(
            ReachyConnectionConfig(mode=RobotConnectionMode.WIRELESS).sdk_connection_mode,
            "network",
        )

    def test_accepts_string_mode_and_trims_host(self) -> None:
        config = ReachyConnectionConfig(mode="wireless", wireless_host=" 192.168.1.8 ")  # type: ignore[arg-type]
        self.assertIs(config.mode, RobotConnectionMode.WIRELESS)
        self.assertEqual(config.wireless_host, "192.168.1.8")

    def test_rejects_url_instead_of_hostname(self) -> None:
        with self.assertRaises(ValueError):
            ReachyConnectionConfig(wireless_host="http://reachy-mini.local")

    def test_exposes_three_start_page_labels(self) -> None:
        options = connection_mode_labels()
        self.assertEqual(len(options), 3)
        self.assertIn(RobotConnectionMode.WIRED, options.values())
        self.assertIn(RobotConnectionMode.WIRELESS, options.values())


class ReachyControllerTests(unittest.TestCase):
    def test_wired_connection_uses_localhost_without_spawning_daemon(self) -> None:
        factory = CapturingFactory("localhost_only", "localhost")
        controller = ReachyController(
            ReachyConnectionConfig(mode=RobotConnectionMode.WIRED), factory=factory
        )

        info = controller.connect()

        self.assertEqual(factory.calls[0]["connection_mode"], "localhost_only")
        self.assertIs(factory.calls[0]["spawn_daemon"], False)
        self.assertEqual(info.host, "localhost")
        self.assertFalse(info.is_wireless)

    def test_wireless_connection_uses_configured_host(self) -> None:
        factory = CapturingFactory("network", "192.168.1.42")
        controller = ReachyController(
            ReachyConnectionConfig(
                mode=RobotConnectionMode.WIRELESS,
                wireless_host="192.168.1.42",
            ),
            factory=factory,
        )

        info = controller.connect()

        self.assertEqual(factory.calls[0]["connection_mode"], "network")
        self.assertEqual(factory.calls[0]["host"], "192.168.1.42")
        self.assertTrue(info.is_wireless)

    def test_auto_reports_the_route_selected_by_sdk(self) -> None:
        factory = CapturingFactory("network", "reachy-mini.local")
        controller = ReachyController(factory=factory)

        info = controller.connect()

        self.assertEqual(factory.calls[0]["connection_mode"], "auto")
        self.assertEqual(info.resolved_mode, "network")

    def test_disconnect_uses_sdk_context_manager_cleanup(self) -> None:
        factory = CapturingFactory("localhost_only", "localhost")
        controller = ReachyController(factory=factory)
        controller.connect()

        controller.disconnect()

        self.assertIsNotNone(factory.robot)
        self.assertTrue(factory.robot.exited)  # type: ignore[union-attr]
        self.assertFalse(controller.is_connected)

    def test_robot_actions_require_connection(self) -> None:
        controller = ReachyController(factory=CapturingFactory("network", "robot"))
        with self.assertRaises(ReachyNotConnectedError):
            controller.wake_up()

    def test_play_sound_validates_file_and_uses_robot_media(self) -> None:
        factory = CapturingFactory("localhost_only", "localhost")
        controller = ReachyController(factory=factory)
        controller.connect()
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "question.wav"
            audio_path.touch()

            controller.play_sound(audio_path)

            self.assertEqual(factory.robot.media.played, [str(audio_path.resolve())])  # type: ignore[union-attr]

    def test_stop_sound_uses_robot_media(self) -> None:
        factory = CapturingFactory("localhost_only", "localhost")
        controller = ReachyController(factory=factory)
        controller.connect()

        controller.stop_sound()

        self.assertTrue(factory.robot.media.stopped)  # type: ignore[union-attr]

    def test_wake_emotion_and_sleep_use_one_persistent_robot(self) -> None:
        factory = CapturingFactory("localhost_only", "localhost")
        emotions = FakeEmotionLibrary()
        controller = ReachyController(
            factory=factory,
            emotion_library_factory=lambda: emotions,
        )
        controller.connect()

        controller.wake_up()
        controller.play_emotion("welcoming1")
        controller.play_emotion("understanding1")
        controller.goto_sleep()

        self.assertIsNotNone(factory.robot)
        self.assertTrue(factory.robot.woke_up)  # type: ignore[union-attr]
        self.assertTrue(factory.robot.went_to_sleep)  # type: ignore[union-attr]
        self.assertEqual(emotions.requested, ["welcoming1", "understanding1"])
        self.assertEqual(
            factory.robot.played_moves,  # type: ignore[union-attr]
            [
                ({"emotion": "welcoming1"}, 0.5, False),
                ({"emotion": "understanding1"}, 0.5, False),
            ],
        )

    def test_emotion_failure_has_an_actionable_message(self) -> None:
        class MissingEmotionLibrary:
            def get(self, _name: str) -> object:
                raise KeyError("missing")

        controller = ReachyController(
            factory=CapturingFactory("localhost_only", "localhost"),
            emotion_library_factory=MissingEmotionLibrary,
        )
        controller.connect()

        with self.assertRaisesRegex(ReachyConnectionError, "unknown-emotion"):
            controller.play_emotion("unknown-emotion")

    def test_wraps_sdk_connection_failure(self) -> None:
        def failing_factory(**_kwargs: object) -> object:
            raise ConnectionError("offline")

        controller = ReachyController(
            ReachyConnectionConfig(mode=RobotConnectionMode.WIRELESS),
            factory=failing_factory,
        )
        with self.assertRaisesRegex(ReachyConnectionError, "wireless Reachy Mini"):
            controller.connect()


if __name__ == "__main__":
    unittest.main()
