import subprocess
import unittest
from unittest import mock

from rogcontrol import hardware


CARDWIRE_GET = """Current Mode: Smart
Available Mode: integrated, hybrid, smart
"""


class CardwireTests(unittest.TestCase):
    def test_parse_status(self):
        current, available = hardware.parse_cardwire_status(CARDWIRE_GET)
        self.assertEqual(current, "Smart")
        self.assertEqual(available, ["Integrated", "Hybrid", "Smart"])

    def test_parse_status_is_tolerant_of_empty_and_unknown_lines(self):
        self.assertEqual(hardware.parse_cardwire_status(""), (None, []))
        self.assertEqual(
            hardware.parse_cardwire_status(
                "cardwired says hello\nCurrent Mode: hybrid\n"),
            ("Hybrid", []),
        )

    @mock.patch("rogcontrol.hardware.subprocess.run")
    def test_read_mode_and_available_modes_use_cardwire_get(self, run):
        run.return_value = subprocess.CompletedProcess(
            ["cardwire", "get"], 0, stdout=CARDWIRE_GET, stderr="")

        self.assertEqual(hardware.read_gpu_mode(), "Smart")
        self.assertEqual(
            hardware.read_supported_gpu_modes(),
            ["Integrated", "Hybrid", "Smart"],
        )
        for call in run.call_args_list:
            self.assertEqual(call.args[0], ["cardwire", "get"])

    @mock.patch("rogcontrol.hardware.subprocess.run")
    def test_set_mode_uses_lowercase_cardwire_cli_value(self, run):
        run.return_value = subprocess.CompletedProcess(
            ["cardwire", "set", "integrated"], 0,
            stdout="Mode has been set to Integrated\n", stderr="")

        ok, message = hardware.set_gpu_mode("Integrated")

        self.assertTrue(ok)
        self.assertIn("Integrated", message)
        self.assertEqual(run.call_args.args[0],
                         ["cardwire", "set", "integrated"])

    def test_mode_choices_include_smart_and_advertised_extras(self):
        self.assertEqual(
            hardware.gpu_mode_choices("Manual", ["Hybrid", "Manual"]),
            ["Integrated", "Hybrid", "Smart", "Manual"],
        )


if __name__ == "__main__":
    unittest.main()
