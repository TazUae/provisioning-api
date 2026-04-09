import unittest


class TestProvisioningApiImports(unittest.TestCase):
    def test_import_provisioning_api(self):
        import provisioning_api

        self.assertIsNotNone(provisioning_api)

    def test_import_provisioning_api_hooks(self):
        import provisioning_api.hooks

        self.assertEqual(provisioning_api.hooks.app_name, "provisioning_api")


if __name__ == "__main__":
    unittest.main()
