"""Docker tests for zMusic."""

import unittest

from scripts.config import AppConfig
from scripts.docker import (
    DockerComposeConfig,
    DockerService,
    create_default_services,
    generate_dev_docker_compose,
    generate_docker_compose,
    generate_dockerfiles,
    generate_env_example,
    generate_requirements_txt,
)


class DockerServiceTest(unittest.TestCase):
    def test_docker_service_creation(self):
        service = DockerService(
            name="test-service",
            image="test:latest",
            ports=["8000:8000"],
            environment={"KEY": "value"},
        )
        self.assertEqual(service.name, "test-service")
        self.assertEqual(service.image, "test:latest")
        self.assertEqual(service.ports, ["8000:8000"])
        self.assertEqual(service.environment, {"KEY": "value"})

    def test_docker_service_defaults(self):
        service = DockerService(name="test", image="test:latest")
        self.assertEqual(service.build_context, ".")
        self.assertEqual(service.dockerfile, "Dockerfile")
        self.assertEqual(service.restart, "unless-stopped")
        self.assertEqual(service.working_dir, "/app")


class DockerComposeConfigTest(unittest.TestCase):
    def test_docker_compose_config_creation(self):
        config = DockerComposeConfig()
        self.assertEqual(config.version, "3.8")
        self.assertEqual(config.services, {})


class CreateDefaultServicesTest(unittest.TestCase):
    def test_create_default_services(self):
        config = AppConfig()
        services = create_default_services(config)

        # Should have all expected services
        expected_services = [
            "api",
            "worker",
            "scheduler",
            "agent-orchestrator",
            "media-worker",
            "stream-worker",
        ]

        for svc_name in expected_services:
            self.assertIn(svc_name, services)
            svc = services[svc_name]
            self.assertEqual(svc.name, svc_name)
            self.assertIsNotNone(svc.image)
            self.assertIsNotNone(svc.dockerfile)


class GenerateDockerComposeTest(unittest.TestCase):
    def test_generate_docker_compose(self):
        config = AppConfig()
        services = create_default_services(config)
        yaml_content = generate_docker_compose(services)

        # Should contain expected sections
        self.assertIn("version: '3.8'", yaml_content)
        self.assertIn("services:", yaml_content)
        self.assertIn("networks:", yaml_content)
        self.assertIn("volumes:", yaml_content)

        # Should contain all services
        for svc_name in services:
            self.assertIn(f"  {svc_name}:", yaml_content)


class GenerateDockerfilesTest(unittest.TestCase):
    def test_generate_dockerfiles(self):
        dockerfiles = generate_dockerfiles()

        expected_files = [
            "Dockerfile",
            "Dockerfile.api",
            "Dockerfile.worker",
            "Dockerfile.scheduler",
            "Dockerfile.agent",
            "Dockerfile.media",
            "Dockerfile.stream",
        ]

        for fname in expected_files:
            self.assertIn(fname, dockerfiles)
            content = dockerfiles[fname]
            self.assertIn("FROM python:3.12-slim", content)
            self.assertIn("ffmpeg", content)
            self.assertIn("zmusic:zmusic", content)
            self.assertIn("USER zmusic", content)


class GenerateRequirementsTxtTest(unittest.TestCase):
    def test_generate_requirements_txt(self):
        content = generate_requirements_txt()
        self.assertIn("psycopg2-binary", content)
        self.assertIn("redis", content)
        self.assertIn("pyyaml", content)
        self.assertIn("pytest", content)
        self.assertIn("psutil", content)


class GenerateEnvExampleTest(unittest.TestCase):
    def test_generate_env_example(self):
        content = generate_env_example()
        self.assertIn("ZMUSIC_DATABASE_URL", content)
        self.assertIn("ZMUSIC_JWT_SECRET", content)
        self.assertIn("ZMUSIC_YOUTUBE_CLIENT_ID", content)
        self.assertIn("ZMUSIC_YOUTUBE_CLIENT_SECRET", content)
        self.assertIn("ZMUSIC_LOG_LEVEL", content)


class GenerateDevDockerComposeTest(unittest.TestCase):
    def test_generate_dev_docker_compose(self):
        content = generate_dev_docker_compose()
        self.assertIn('version: "3.8"', content)
        self.assertIn("services:", content)
        self.assertIn("api:", content)
        self.assertIn("worker:", content)
        self.assertIn("scheduler:", content)
        self.assertIn("media-worker:", content)
        self.assertIn("stream-worker:", content)
        self.assertIn("redis:", content)
        self.assertIn("profiles:", content)


if __name__ == "__main__":
    unittest.main()
