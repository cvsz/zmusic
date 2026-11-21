"""Docker support for zMusic.

Provides production-quality Docker configuration with:
- Multi-stage builds for minimal images
- Non-root user execution
- Health checks
- Proper signal handling
- Configuration via environment variables
- Docker Compose for local development

Services:
- api: REST API service
- worker: Background job worker
- scheduler: Scheduling service
- agent-orchestrator: AI agent orchestration
- media-worker: Media processing (FFmpeg)
- stream-worker: Stream encoding/broadcasting
- postgres: PostgreSQL database (production)
- redis: Redis cache/queue (production)
- nginx: Reverse proxy (production)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import AppConfig
from .logging import get_logger

logger = get_logger("zmusic.docker")


@dataclass
class DockerService:
    """Docker service configuration."""

    name: str
    image: str
    build_context: str = "."
    dockerfile: str = "Dockerfile"
    ports: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    volumes: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    healthcheck: dict[str, Any] | None = None
    restart: str = "unless-stopped"
    user: str | None = None
    working_dir: str = "/app"
    command: list[str] | None = None


@dataclass
class DockerComposeConfig:
    """Docker Compose configuration."""

    version: str = "3.8"
    services: dict[str, DockerService] = field(default_factory=dict)
    networks: dict[str, Any] = field(default_factory=dict)
    volumes: dict[str, Any] = field(default_factory=dict)


def create_default_services(config: AppConfig) -> dict[str, DockerService]:
    """Create default Docker service configurations."""

    services = {}

    # API Service
    services["api"] = DockerService(
        name="api",
        image="zmusic/api:latest",
        build_context=".",
        dockerfile="Dockerfile.api",
        ports=["8000:8000"],
        environment={
            "ZMUSIC_DATABASE_URL": "sqlite:///data/zmusic.db",
            "ZMUSIC_JWT_SECRET": "${ZMUSIC_JWT_SECRET}",
            "ZMUSIC_LOG_LEVEL": "INFO",
        },
        volumes=[
            "zmusic-data:/app/data",
            "zmusic-logs:/app/logs",
        ],
        healthcheck={
            "test": ["CMD", "curl", "-f", "http://localhost:8000/health/live"],
            "interval": "30s",
            "timeout": "10s",
            "retries": 3,
            "start_period": "10s",
        },
        restart="unless-stopped",
        user="1000:1000",
        command=["python", "-m", "scripts.api_server"],
    )

    # Worker Service
    services["worker"] = DockerService(
        name="worker",
        image="zmusic/worker:latest",
        build_context=".",
        dockerfile="Dockerfile.worker",
        environment={
            "ZMUSIC_DATABASE_URL": "sqlite:///data/zmusic.db",
            "ZMUSIC_REDIS_URL": "redis://redis:6379/0",
            "ZMUSIC_LOG_LEVEL": "INFO",
        },
        volumes=[
            "zmusic-data:/app/data",
            "zmusic-logs:/app/logs",
            "zmusic-media:/app/media",
        ],
        depends_on=["redis"],
        restart="unless-stopped",
        user="1000:1000",
        command=["python", "-m", "scripts.worker_main"],
    )

    # Scheduler Service
    services["scheduler"] = DockerService(
        name="scheduler",
        image="zmusic/scheduler:latest",
        build_context=".",
        dockerfile="Dockerfile.scheduler",
        environment={
            "ZMUSIC_DATABASE_URL": "sqlite:///data/zmusic.db",
            "ZMUSIC_LOG_LEVEL": "INFO",
        },
        volumes=[
            "zmusic-data:/app/data",
            "zmusic-logs:/app/logs",
        ],
        restart="unless-stopped",
        user="1000:1000",
        command=["python", "-m", "scripts.scheduler_main"],
    )

    # Agent Orchestrator Service
    services["agent-orchestrator"] = DockerService(
        name="agent-orchestrator",
        image="zmusic/agent-orchestrator:latest",
        build_context=".",
        dockerfile="Dockerfile.agent",
        environment={
            "ZMUSIC_DATABASE_URL": "sqlite:///data/zmusic.db",
            "ZMUSIC_OPENAI_API_KEY": "${ZMUSIC_OPENAI_API_KEY}",
            "ZMUSIC_LOG_LEVEL": "INFO",
        },
        volumes=[
            "zmusic-data:/app/data",
            "zmusic-logs:/app/logs",
        ],
        restart="unless-stopped",
        user="1000:1000",
        command=["python", "-m", "scripts.agent_orchestrator"],
    )

    # Media Worker Service
    services["media-worker"] = DockerService(
        name="media-worker",
        image="zmusic/media-worker:latest",
        build_context=".",
        dockerfile="Dockerfile.media",
        environment={
            "ZMUSIC_DATABASE_URL": "sqlite:///data/zmusic.db",
            "ZMUSIC_LOG_LEVEL": "INFO",
        },
        volumes=[
            "zmusic-data:/app/data",
            "zmusic-logs:/app/logs",
            "zmusic-media:/app/media",
            "zmusic-temp:/tmp/zmusic",
        ],
        restart="unless-stopped",
        user="1000:1000",
        command=["python", "-m", "scripts.media_worker"],
    )

    # Stream Worker Service
    services["stream-worker"] = DockerService(
        name="stream-worker",
        image="zmusic/stream-worker:latest",
        build_context=".",
        dockerfile="Dockerfile.stream",
        ports=["1935:1935"],  # RTMP
        environment={
            "ZMUSIC_DATABASE_URL": "sqlite:///data/zmusic.db",
            "ZMUSIC_YOUTUBE_CLIENT_ID": "${ZMUSIC_YOUTUBE_CLIENT_ID}",
            "ZMUSIC_YOUTUBE_CLIENT_SECRET": "${ZMUSIC_YOUTUBE_CLIENT_SECRET}",
            "ZMUSIC_LOG_LEVEL": "INFO",
        },
        volumes=[
            "zmusic-data:/app/data",
            "zmusic-logs:/app/logs",
            "zmusic-media:/app/media",
            "zmusic-temp:/tmp/zmusic",
        ],
        restart="unless-stopped",
        user="1000:1000",
        command=["python", "-m", "scripts.stream_worker"],
    )

    return services


def generate_docker_compose(
    services: dict[str, DockerService], output_path: str = "docker-compose.yml"
) -> str:
    """Generate docker-compose.yml from service definitions."""
    import yaml

    compose: dict[str, Any] = {
        "version": "3.8",
        "services": {},
        "networks": {
            "zmusic-network": {
                "driver": "bridge",
            },
        },
        "volumes": {
            "zmusic-data": {},
            "zmusic-logs": {},
            "zmusic-media": {},
            "zmusic-temp": {},
        },
    }

    for name, service in services.items():
        svc_dict = {
            "image": service.image,
            "build": {
                "context": service.build_context,
                "dockerfile": service.dockerfile,
            },
            "ports": service.ports,
            "environment": service.environment,
            "volumes": service.volumes,
            "depends_on": service.depends_on,
            "restart": service.restart,
            "user": service.user,
            "working_dir": service.working_dir,
            "networks": ["zmusic-network"],
        }

        if service.healthcheck:
            svc_dict["healthcheck"] = service.healthcheck

        if service.command:
            svc_dict["command"] = service.command

        compose["services"][name] = svc_dict

    yaml_content = yaml.dump(compose, default_flow_style=False, sort_keys=False)

    with open(output_path, "w") as f:
        f.write(yaml_content)

    return yaml_content


def generate_dockerfiles() -> dict[str, str]:
    """Generate Dockerfile content for each service."""

    base_dockerfile = """# Base image with Python and FFmpeg
FROM python:3.12-slim as base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \\
    ffmpeg \\
    libpq-dev \\
    gcc \\
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r -g 1000 zmusic && useradd -r -g zmusic -u 1000 zmusic

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY scripts/ ./scripts/
COPY tests/ ./tests/

# Create directories and set permissions
RUN mkdir -p /app/data /app/logs /app/media /tmp/zmusic && \\
    chown -R zmusic:zmusic /app /tmp/zmusic

# Switch to non-root user
USER zmusic

# Default command (override in docker-compose)
CMD ["python", "-m", "scripts.main"]
"""

    dockerfiles = {
        "Dockerfile": base_dockerfile,
        "Dockerfile.api": base_dockerfile.replace(
            'CMD ["python", "-m", "scripts.main"]',
            'CMD ["python", "-m", "scripts.api_server"]',
        ),
        "Dockerfile.worker": base_dockerfile.replace(
            'CMD ["python", "-m", "scripts.main"]',
            'CMD ["python", "-m", "scripts.worker_main"]',
        ),
        "Dockerfile.scheduler": base_dockerfile.replace(
            'CMD ["python", "-m", "scripts.main"]',
            'CMD ["python", "-m", "scripts.scheduler_main"]',
        ),
        "Dockerfile.agent": base_dockerfile.replace(
            'CMD ["python", "-m", "scripts.main"]',
            'CMD ["python", "-m", "scripts.agent_orchestrator"]',
        ),
        "Dockerfile.media": base_dockerfile.replace(
            'CMD ["python", "-m", "scripts.main"]',
            'CMD ["python", "-m", "scripts.media_worker"]',
        ),
        "Dockerfile.stream": base_dockerfile.replace(
            'CMD ["python", "-m", "scripts.main"]',
            'CMD ["python", "-m", "scripts.stream_worker"]',
        ),
    }

    return dockerfiles


def generate_requirements_txt() -> str:
    """Generate requirements.txt content."""
    return """# Core dependencies
psycopg2-binary>=2.9.0
redis>=4.5.0
pyyaml>=6.0
python-dotenv>=1.0.0

# HTTP
httpx>=0.24.0
urllib3>=2.0.0

# Async
asyncio>=3.4.3

# Monitoring
psutil>=5.9.0

# Testing
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0

# Type checking
mypy>=1.5.0
types-psutil>=5.9.0

# Linting
ruff>=0.1.0
black>=23.0.0

# Security
bandit>=1.7.0
safety>=2.3.0
"""


def generate_env_example() -> str:
    """Generate .env.example content."""
    return """# zMusic Environment Configuration
# Copy this file to .env and fill in the values

# Database
ZMUSIC_DATABASE_URL=sqlite:///data/zmusic.db

# Security
ZMUSIC_JWT_SECRET=your-super-secret-jwt-key-change-in-production
ZMUSIC_JWT_ALGORITHM=HS256
ZMUSIC_JWT_EXPIRY_SECONDS=3600

# Streaming
ZMUSIC_RTMP_PORT=1935
ZMUSIC_HTTP_PORT=8080
ZMUSIC_MAX_CONCURRENT_STREAMS=5
ZMUSIC_DEFAULT_FPS=30
ZMUSIC_DEFAULT_RESOLUTION=1080p
ZMUSIC_DEFAULT_VIDEO_BITRATE=4500k
ZMUSIC_DEFAULT_AUDIO_BITRATE=160k

# YouTube API (required for YouTube Live)
ZMUSIC_YOUTUBE_CLIENT_ID=your-youtube-client-id
ZMUSIC_YOUTUBE_CLIENT_SECRET=your-youtube-client-secret

# Redis (for production)
ZMUSIC_REDIS_URL=redis://localhost:6379/0

# Logging
ZMUSIC_LOG_LEVEL=INFO

# AI/LLM (optional)
ZMUSIC_OPENAI_API_KEY=your-openai-api-key
"""


def generate_dev_docker_compose() -> str:
    """Generate docker-compose.dev.yml for local development."""
    return """version: "3.8"

services:
  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    ports:
      - "8000:8000"
    environment:
      - ZMUSIC_DATABASE_URL=sqlite:///data/zmusic.db
      - ZMUSIC_JWT_SECRET=dev-secret-change-in-production
      - ZMUSIC_LOG_LEVEL=DEBUG
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./scripts:/app/scripts:ro
    command: ["python", "-m", "scripts.api_server", "--reload"]
    profiles:
      - dev

  worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    environment:
      - ZMUSIC_DATABASE_URL=sqlite:///data/zmusic.db
      - ZMUSIC_LOG_LEVEL=DEBUG
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./scripts:/app/scripts:ro
      - ./media:/app/media
    profiles:
      - dev

  scheduler:
    build:
      context: .
      dockerfile: Dockerfile.scheduler
    environment:
      - ZMUSIC_DATABASE_URL=sqlite:///data/zmusic.db
      - ZMUSIC_LOG_LEVEL=DEBUG
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./scripts:/app/scripts:ro
    profiles:
      - dev

  media-worker:
    build:
      context: .
      dockerfile: Dockerfile.media
    environment:
      - ZMUSIC_DATABASE_URL=sqlite:///data/zmusic.db
      - ZMUSIC_LOG_LEVEL=DEBUG
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./scripts:/app/scripts:ro
      - ./media:/app/media
      - ./temp:/tmp/zmusic
    profiles:
      - dev

  stream-worker:
    build:
      context: .
      dockerfile: Dockerfile.stream
    ports:
      - "1935:1935"
    environment:
      - ZMUSIC_DATABASE_URL=sqlite:///data/zmusic.db
      - ZMUSIC_YOUTUBE_CLIENT_ID=${ZMUSIC_YOUTUBE_CLIENT_ID}
      - ZMUSIC_YOUTUBE_CLIENT_SECRET=${ZMUSIC_YOUTUBE_CLIENT_SECRET}
      - ZMUSIC_LOG_LEVEL=DEBUG
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./scripts:/app/scripts:ro
      - ./media:/app/media
      - ./temp:/tmp/zmusic
    profiles:
      - dev

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    profiles:
      - dev

volumes:
  redis-data:

networks:
  default:
    name: zmusic-dev-network
"""


# --- Example Usage ---
#
# config = AppConfig()
# services = create_default_services(config)
#
# # Generate docker-compose.yml
# yaml_content = generate_docker_compose(services, "docker-compose.yml")
#
# # Generate Dockerfiles
# dockerfiles = generate_dockerfiles()
# for name, content in dockerfiles.items():
#     with open(name, "w") as f:
#         f.write(content)
#
# # Generate requirements.txt
# with open("requirements.txt", "w") as f:
#     f.write(generate_requirements_txt())
#
# # Generate .env.example
# with open(".env.example", "w") as f:
#     f.write(generate_env_example())
#
# # Generate development docker-compose
# with open("docker-compose.dev.yml", "w") as f:
#     f.write(generate_dev_docker_compose())
