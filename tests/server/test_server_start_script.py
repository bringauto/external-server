import unittest
import sys
import argparse

from external_server_main import parsed_script_args


class Test_Argparse_Init(unittest.TestCase):

    def test_omitting_all_arguments_sets_default_values_for_config_file_path_and_tls(self):
        sys.argv = ["external_server_main.py"]
        args = parsed_script_args()
        self.assertEqual(args.config, "./config/config.json")
        self.assertEqual(args.tls, None)

    def test_setting_existing_config_file_path_is_allowed(self):
        sys.argv = ["external_server_main.py", "-c", "./config/config.json"]
        args = parsed_script_args()
        self.assertEqual(args.config, "./config/config.json")
        self.assertEqual(args.tls, None)

    def test_setting_nonexistent_config_file_path_raises_error(self):
        sys.argv = ["external_server_main.py", "-c", "./nonexistent_folder/some_config.json"]
        with self.assertRaises(FileNotFoundError):
            parsed_script_args()

    def test_setting_tls_flag_without_further_arguments_raises_error(self):
        with self.assertRaises(argparse.ArgumentError) as e:
            sys.argv = ["external_server_main.py", "--tls"]
            parsed_script_args()
            self.assertIn(e.msg, "ca certificate")
            self.assertIn(e.msg, "PEM encoded client certificate")
            self.assertIn(e.msg, "private key to PEM encoded client certificate")

    def test_setting_tls_flag_with_only_ca_certificate_missing_raises_error(self):
        with self.assertRaises(argparse.ArgumentError) as e:
            sys.argv = ["external_server_main.py", "--tls"]
            parsed_script_args()
            self.assertIn(e.msg, "ca certificate")
            self.assertNotIn(e.msg, "PEM encoded client certificate")
            self.assertNotIn(e.msg, "private key to PEM encoded client certificate")

    def test_setting_tls_flag_with_only_PEM_certificate_missing_raises_error(self):
        with self.assertRaises(argparse.ArgumentError) as e:
            sys.argv = ["external_server_main.py", "--tls"]
            parsed_script_args()
            self.assertNotIn(e.msg, "ca certificate")
            self.assertIn(e.msg, "PEM encoded client certificate")
            self.assertNotIn(e.msg, "private key to PEM encoded client certificate")

    def test_setting_tls_flag_with_only_private_key_missing_raises_error(self):
        with self.assertRaises(argparse.ArgumentError) as e:
            sys.argv = ["external_server_main.py", "--tls"]
            parsed_script_args()
            self.assertNotIn(e.msg, "ca certificate")
            self.assertNotIn(e.msg, "PEM encoded client certificate")
            self.assertIn(e.msg, "private key to PEM encoded client certificate")

    def test_setting_tls_flag_with_ca_cert_cert_and_key_is_allowed(self):
        sys.argv = ["external_server_main.py", "--tls", "--ca", "ca.pem", "--cert", "cert.pem", "--key", "key.pem"]
        args = parsed_script_args()
        self.assertEqual(args.config, "./config/config.json")
        self.assertEqual(args.tls, True)
        self.assertEqual(args.ca, "ca.pem")
        self.assertEqual(args.cert, "cert.pem")
        self.assertEqual(args.key, "key.pem")


if __name__=="__main__":  # pragma: no cover
    unittest.main()