import unittest
import sys
import argparse

sys.path.append(".")

from external_server.__main__ import parsed_script_args


class Test_Argparse_Init(unittest.TestCase):

    def test_setting_existing_config_file_path_is_allowed(self):
        sys.argv = ["external_server_main.py", "-c", "./tests/config.json"]
        args = parsed_script_args()
        self.assertEqual(args.config, "./tests/config.json")
        self.assertIsNone(args.tls)

    def test_setting_nonexistent_config_file_path_raises_error(self):
        sys.argv = ["external_server_main.py", "-c", "./nonexistent_folder/some_config.json"]
        with self.assertRaises(FileNotFoundError):
            parsed_script_args()

    def test_setting_tls_flag_without_further_arguments_raises_error(self):
        with self.assertRaises(argparse.ArgumentError) as cm:
            sys.argv = ["external_server_main.py", "-c", "./tests/config.json", "--tls"]
            parsed_script_args()
        self.assertIn("ca certificate", cm.exception.message)
        self.assertIn("PEM encoded client certificate", cm.exception.message)
        self.assertIn("private key to PEM encoded client certificate", cm.exception.message)

    def test_setting_tls_flag_with_only_ca_certificate_missing_raises_error(self):
        with self.assertRaises(argparse.ArgumentError) as cm:
            sys.argv = [
                "external_server_main.py",
                "-c",
                "./tests/config.json",
                "--tls",
                "--cert",
                "cert.pem",
                "--key",
                "key.pem",
            ]
            parsed_script_args()
        self.assertIn("ca certificate", cm.exception.message)
        self.assertNotIn("PEM encoded client certificate", cm.exception.message)
        self.assertNotIn("private key to PEM encoded client certificate", cm.exception.message)

    def test_setting_tls_flag_with_only_PEM_certificate_missing_raises_error(self):
        with self.assertRaises(argparse.ArgumentError) as cm:
            sys.argv = [
                "external_server_main.py",
                "-c",
                "./tests/config.json",
                "--tls",
                "--ca",
                "ca.pem",
                "--key",
                "key.pem",
            ]
            parsed_script_args()
        self.assertNotIn("ca certificate", cm.exception.message)
        self.assertIn("PEM encoded client certificate", cm.exception.message)
        self.assertNotIn("private key to PEM encoded client certificate", cm.exception.message)

    def test_setting_tls_flag_with_only_private_key_missing_raises_error(self):
        with self.assertRaises(argparse.ArgumentError) as cm:
            sys.argv = [
                "external_server_main.py",
                "-c",
                "./tests/config.json",
                "--tls",
                "--cert",
                "cert.pem",
                "--ca",
                "ca.pem",
            ]
            parsed_script_args()
        self.assertNotIn("ca certificate", cm.exception.message)
        self.assertIn("private key", cm.exception.message)

    def test_setting_tls_flag_with_ca_cert_cert_and_key_is_allowed(self):
        sys.argv = [
            "external_server_main.py",
            "-c",
            "./tests/config.json",
            "--tls",
            "--ca",
            "ca.pem",
            "--cert",
            "cert.pem",
            "--key",
            "key.pem",
        ]
        args = parsed_script_args()
        self.assertTrue(args.tls)
        self.assertEqual(args.ca, "ca.pem")
        self.assertEqual(args.cert, "cert.pem")
        self.assertEqual(args.key, "key.pem")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
