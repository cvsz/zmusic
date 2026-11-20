# STREMDBC — AI MUSIC LIVE BROADCASTING
## MASTER BUILD PROMPT — AUTONOMOUS CONTENT + STREAMING PLATFORM

You are the Principal Architect, Staff+ Backend Engineer, Streaming Engineer, DevOps Engineer, AI Agent Engineer, QA Engineer, Security Engineer, and SRE responsible for transforming the STREMDBC repository into a production-grade AI-powered music live broadcasting platform.

Your objective is to build a system capable of planning, generating/assembling, validating, scheduling, composing, broadcasting, monitoring, recovering, and analyzing continuous music livestreams for YouTube Live.

Do not merely create a demo.

Build a runnable, testable, modular production system.

---

# 1. PRIMARY OBJECTIVE

Transform STREMDBC into:

> **An AI-native 24/7 music broadcasting platform capable of automatically creating programming schedules, assembling legally usable music and visual assets, producing livestream compositions, broadcasting through RTMP, monitoring stream health, recovering failures, and learning from analytics.**

The system must support:

- music livestreams
- long-form continuous broadcasts
- scheduled broadcasts
- recurring broadcasts
- multiple channels
- multiple concurrent streams
- playlists
- themed programming
- visual loops
- overlays
- now-playing information
- stream metadata
- automated monitoring
- automatic recovery
- analytics
- content lifecycle management
- rights/licensing validation
- human approval workflows
- AI-assisted optimization

---

# 2. ENGINEERING PRINCIPLE

Do NOT build one giant AI agent.

Use an orchestrated multi-agent architecture.

```text
                    AI ORCHESTRATOR
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
     CONTENT AGENTS   ASSET AGENTS    STREAM AGENTS
          |                |                |
          +----------------+----------------+
                           |
                           v
                  CONTENT COMPOSER
                           |
                           v
                    STREAM ENGINE
                           |
                           v
                      RTMP OUTPUT
                           |
                           v
                    YOUTUBE LIVE
                           |
          +----------------+----------------+
          |                                 |
          v                                 v
     LIVE MONITOR                      ANALYTICS
          |                                 |
          +----------------+----------------+
                           |
                           v
                    OPTIMIZATION
```

The AI layer controls decisions.

The deterministic streaming layer executes them.

Never allow an LLM to directly control critical infrastructure without validation.

---

# 3. ARCHITECTURAL LAYERS

Implement these layers:

```text
LAYER 1 — API
LAYER 2 — AUTHORIZATION
LAYER 3 — CONTROL PLANE
LAYER 4 — AI AGENT ORCHESTRATION
LAYER 5 — CONTENT MANAGEMENT
LAYER 6 — ASSET MANAGEMENT
LAYER 7 — MEDIA PIPELINE
LAYER 8 — STREAM ENGINE
LAYER 9 — YOUTUBE INTEGRATION
LAYER 10 — MONITORING
LAYER 11 — ANALYTICS
LAYER 12 — STORAGE
LAYER 13 — WORKER SYSTEM
LAYER 14 — SECURITY
```

Keep responsibilities separate.

---

# 4. CORE SERVICES

Implement or refactor the platform around these logical services.

## 4.1 API Service

Responsibilities:

- REST API
- authentication
- authorization
- channel management
- content management
- playlist management
- stream management
- scheduling
- agent control
- analytics
- health endpoints

---

## 4.2 Agent Orchestrator

Create an Agent Orchestrator responsible for:

- creating jobs
- dispatching agents
- tracking state
- handling retries
- enforcing policies
- validating agent output
- maintaining execution history
- preventing duplicate jobs
- handling failures

Use explicit state machines.

Example:

```text
CREATED
  ↓
PLANNED
  ↓
GENERATING
  ↓
VALIDATING
  ↓
READY
  ↓
SCHEDULED
  ↓
STREAMING
  ↓
COMPLETED
```

Failure state:

```text
FAILED
  ↓
RETRY_PENDING
  ↓
RECOVERING
  ↓
VALIDATING
```

Do not rely on natural-language state.

---

# 5. AGENT SYSTEM

Implement the following agents.

## 5.1 Music Director Agent

Responsibilities:

- determine musical theme
- genre
- mood
- BPM range
- session duration
- energy curve
- track ordering
- transition strategy
- target audience profile

Input:

```json
{
  "theme": "late night rain",
  "genre": "lofi",
  "duration_hours": 6,
  "target_mood": "calm"
}
```

Output must be structured JSON.

---

# 5.2 Music Production Agent

Responsibilities:

- select approved music
- generate music jobs where supported
- assemble playlists
- normalize metadata
- calculate duration
- detect gaps
- validate audio
- prepare transitions

Never use unauthorized copyrighted music.

Every track must have a rights record.

---

# 5.3 Rights Validation Agent

This is mandatory.

Validate:

- ownership
- license
- commercial-use permission
- YouTube permission
- attribution requirements
- expiration
- geographic restrictions

Example:

```json
{
  "track_id": "track_001",
  "youtube_allowed": true,
  "commercial_allowed": true,
  "license_valid_until": null,
  "attribution_required": false
}
```

A stream must not enter production if required rights validation fails.

---

# 5.4 Visual Director Agent

Create visual programming.

Examples:

- rainy city
- cyberpunk city
- ocean
- fireplace
- abstract particles
- space
- nature
- study room
- night drive
- sunrise

Output:

```json
{
  "visual_theme": "rainy_tokyo_night",
  "camera_motion": "slow",
  "loop_duration_seconds": 1200,
  "overlay_style": "minimal"
}
```

---

# 5.5 Visual Asset Agent

Responsibilities:

- generate or select visual assets
- create loops
- validate dimensions
- validate frame rate
- detect missing assets
- prepare media cache

Support:

- images
- videos
- animated backgrounds
- overlays
- logos
- lower thirds

---

# 5.6 Brand Agent

Responsibilities:

- channel identity
- logo
- typography
- overlays
- colors
- watermark
- title cards
- now-playing graphics

Brand configuration must be stored rather than embedded in agent prompts.

---

# 5.7 Content Composer Agent

Combine:

```text
AUDIO
+
VIDEO
+
OVERLAYS
+
NOW PLAYING
+
TRANSITIONS
+
BRANDING
```

Output a deterministic media composition plan.

Example:

```json
{
  "audio_playlist": "playlist_001",
  "visual_scene": "scene_004",
  "overlay": "overlay_001",
  "now_playing": true,
  "transition": "crossfade"
}
```

The agent creates the plan.

FFmpeg executes the plan.

---

# 5.8 Metadata Agent

Generate:

- YouTube title
- description
- tags
- category recommendation
- stream description
- playlist description
- pinned-message suggestion
- chapter metadata where applicable

Do not fabricate facts.

Do not claim music is original unless rights metadata confirms it.

---

# 5.9 Scheduler Agent

Support:

- one-time streams
- recurring streams
- daily programming
- weekly programming
- 24/7 channels
- time-zone aware schedules

Example:

```text
00:00–06:00 Night Lo-Fi
06:00–09:00 Morning Chill
09:00–12:00 Focus
12:00–18:00 Ambient
18:00–00:00 Night Drive
```

---

# 5.10 Stream Engineer Agent

Responsibilities:

- generate stream configuration
- validate encoder settings
- configure FFmpeg
- configure RTMP
- calculate bitrate
- validate audio/video compatibility
- preflight stream

The agent must never blindly execute generated shell commands.

Commands must pass deterministic validation.

---

# 5.11 Live Monitor Agent

Monitor:

- RTMP connectivity
- encoder health
- CPU
- RAM
- GPU where available
- FPS
- bitrate
- dropped frames
- audio silence
- audio clipping
- process health
- disk space
- stream duration

Example:

```text
STREAM HEALTH
--------------------------------
RTMP             HEALTHY
Video FPS        30
Bitrate          4500 kbps
Dropped Frames   0.02%
Audio            HEALTHY
Encoder          HEALTHY
Disk             72%
CPU              41%
--------------------------------
```

---

# 5.12 Recovery Agent

Automatically recover from:

- FFmpeg crash
- network interruption
- RTMP disconnect
- encoder failure
- audio failure
- visual pipeline failure
- worker failure

Use bounded retries.

Never create infinite restart loops.

Example:

```text
FAILURE
  ↓
CLASSIFY
  ↓
RESTART COMPONENT
  ↓
HEALTH CHECK
  ↓
RECONNECT
  ↓
VERIFY
```

Escalate persistent failures.

---

# 5.13 Analytics Agent

Collect:

- concurrent viewers
- watch time
- average view duration
- retention
- stream duration
- engagement
- peak viewers
- stream interruptions
- content performance

Generate post-stream reports.

---

# 5.14 Optimization Agent

Use analytics to recommend:

- better schedules
- stronger themes
- improved titles
- improved thumbnails
- playlist changes
- visual changes
- stream duration
- programming changes

Never automatically make high-impact changes without policy approval.

---

# 6. DATA MODEL

Implement database models for at least:

```text
users
organizations
channels
channel_settings

agents
agent_runs
agent_tasks

content
content_versions
playlists
playlist_items

tracks
track_metadata
track_rights

visual_assets
audio_assets
overlay_assets

scenes
compositions

streams
stream_sessions
stream_events
stream_health

schedules
schedule_items

youtube_accounts
youtube_channels

analytics
analytics_snapshots

jobs
job_attempts

audit_logs
system_events
```

Use foreign keys.

Use indexes.

Use timestamps.

Use UUIDs.

Implement soft deletion where appropriate.

---

# 7. CONTENT STATE MACHINE

Content must have explicit states.

```text
DRAFT
↓
GENERATING
↓
VALIDATING
↓
APPROVED
↓
READY
↓
SCHEDULED
↓
ACTIVE
↓
COMPLETED
```

Failure:

```text
VALIDATION_FAILED
CONTENT_FAILED
STREAM_FAILED
```

Never allow invalid content to become READY.

---

# 8. STREAM STATE MACHINE

```text
CREATED
↓
PREFLIGHT
↓
READY
↓
STARTING
↓
LIVE
↓
DEGRADED
↓
RECOVERING
↓
LIVE
↓
STOPPING
↓
STOPPED
```

Persistent failure:

```text
FAILED
```

Every state transition must be logged.

---

# 9. MEDIA PIPELINE

Use FFmpeg as the deterministic media engine unless the existing STREMDBC architecture provides a better production implementation.

Support:

- H.264
- AAC
- MP4
- MPEG-TS where appropriate
- RTMP
- configurable FPS
- configurable resolution
- configurable bitrate
- audio normalization
- looping video
- playlist playback
- transitions

Provide safe presets.

Example:

```yaml
profiles:

  youtube_1080p:
    width: 1920
    height: 1080
    fps: 30
    video_bitrate: 4500k
    audio_bitrate: 160k

  youtube_720p:
    width: 1280
    height: 720
    fps: 30
    video_bitrate: 2500k
    audio_bitrate: 128k
```

Make encoder settings configurable.

---

# 10. GAPLESS PLAYBACK

A music broadcast must not unexpectedly stop between tracks.

Implement:

- playlist preloading
- transition preparation
- crossfade where supported
- silence detection
- fallback track
- emergency playlist

Maintain:

```text
CURRENT TRACK
NEXT TRACK
BACKUP TRACK
```

---

# 11. EMERGENCY CONTENT

Every live channel must have an emergency fallback.

Example:

```text
Primary playlist
      ↓
Backup playlist
      ↓
Emergency visual
      ↓
Emergency audio
```

The stream should remain operational whenever possible.

---

# 12. YOUTUBE INTEGRATION

Implement YouTube integration behind an abstraction.

Required capabilities:

```text
OAuth
channel discovery
stream creation
broadcast creation
stream binding
metadata update
live status
stream status
broadcast status
```

Never hard-code API credentials.

Use environment variables or secret management.

---

# 13. SECURITY

Implement:

- authentication
- RBAC
- API authorization
- secret isolation
- encrypted sensitive configuration
- audit logs
- rate limiting
- input validation
- command validation
- SSRF protection
- path traversal protection
- upload validation
- MIME validation
- file-size limits

Never allow arbitrary agent-generated shell execution.

Dangerous commands must be blocked.

---

# 14. AI SAFETY / EXECUTION POLICY

LLMs may:

```text
PLAN
CLASSIFY
GENERATE
RECOMMEND
ANALYZE
```

Deterministic services must:

```text
EXECUTE
VALIDATE
STORE
TRANSMIT
```

AI output must always pass schema validation.

Example:

```text
LLM
 ↓
JSON Schema
 ↓
Policy Engine
 ↓
Validator
 ↓
Executor
```

Never:

```text
LLM → shell → production
```

---

# 15. WORKER ARCHITECTURE

Use asynchronous workers.

Suggested queues:

```text
content-generation
music-processing
visual-processing
composition
stream-start
stream-stop
stream-monitor
analytics
optimization
recovery
```

Every job needs:

```text
job_id
type
priority
status
attempt
created_at
started_at
completed_at
error
payload
```

Implement retries with exponential backoff.

---

# 16. OBSERVABILITY

Implement:

### Logs

Structured JSON logs.

### Metrics

At minimum:

```text
stream_active
stream_duration
stream_bitrate
stream_fps
stream_dropped_frames
stream_reconnects

agent_jobs
agent_failures
agent_latency

queue_depth
worker_health

cpu_usage
memory_usage
disk_usage
```

### Health endpoints

```text
/health
/health/live
/health/ready
/metrics
```

---

# 17. ADMIN DASHBOARD

Create an operational dashboard.

Dashboard sections:

```text
OVERVIEW
CHANNELS
LIVE STREAMS
CONTENT
PLAYLISTS
MUSIC
VISUALS
SCHEDULE
AGENTS
JOBS
ANALYTICS
SYSTEM
SETTINGS
```

Live stream page:

```text
+------------------------------------------+
| CHANNEL                                  |
| LIVE                                     |
+------------------------------------------+
| Preview                                  |
|                                          |
+-------------------+----------------------+
| Viewers           | Bitrate              |
| FPS               | Dropped Frames       |
| CPU               | Memory               |
+-------------------+----------------------+
| Current Track                            |
| Next Track                               |
+------------------------------------------+
```

---

# 18. CHANNEL CONFIGURATION

Each channel must be independently configurable.

Example:

```yaml
channel:
  name: "Night Radio"

  programming:
    mode: "autonomous"

  music:
    genres:
      - lofi
      - ambient
      - chill

  visual:
    theme: "rainy_city"

  stream:
    resolution: "1080p"
    fps: 30

  schedule:
    timezone: "Asia/Bangkok"
```

---

# 19. AUTONOMOUS MODE

Implement:

```text
AUTONOMOUS MODE
```

The system should be able to:

1. inspect channel configuration
2. generate programming plan
3. select approved assets
4. validate rights
5. compose media
6. generate metadata
7. schedule stream
8. start stream
9. monitor stream
10. recover failures
11. collect analytics
12. produce report
13. improve next programming cycle

Human approval must remain configurable.

Modes:

```text
MANUAL
ASSISTED
AUTONOMOUS
```

---

# 20. HUMAN APPROVAL

Support approval gates.

Examples:

```text
CONTENT APPROVAL
RIGHTS APPROVAL
STREAM APPROVAL
METADATA APPROVAL
```

Channel policy determines which gates are required.

---

# 21. API DESIGN

Create REST endpoints similar to:

```text
GET    /api/v1/channels
POST   /api/v1/channels

GET    /api/v1/content
POST   /api/v1/content

GET    /api/v1/playlists
POST   /api/v1/playlists

GET    /api/v1/assets
POST   /api/v1/assets

GET    /api/v1/schedules
POST   /api/v1/schedules

GET    /api/v1/streams
POST   /api/v1/streams/{id}/start
POST   /api/v1/streams/{id}/stop

GET    /api/v1/streams/{id}/health

GET    /api/v1/agents
POST   /api/v1/agents/{id}/run

GET    /api/v1/jobs

GET    /api/v1/analytics
```

Use API versioning.

---

# 22. EVENT SYSTEM

Publish domain events.

Examples:

```text
content.created
content.validated
content.approved

stream.created
stream.started
stream.degraded
stream.recovered
stream.failed
stream.stopped

track.started
track.completed

agent.started
agent.completed
agent.failed

rights.validation.failed
```

Make events idempotent.

---

# 23. IDEMPOTENCY

Every externally triggered operation must be safe to retry.

For example:

```text
START STREAM
```

must not create multiple simultaneous encoders.

Use locks/idempotency keys.

---

# 24. RESOURCE MANAGEMENT

Streaming is resource intensive.

Implement:

- CPU limits
- memory limits
- worker concurrency
- stream concurrency limits
- disk quotas
- asset cleanup
- temporary-file cleanup
- process supervision

Before starting a stream:

```text
CHECK RESOURCES
      ↓
CHECK ASSETS
      ↓
CHECK RIGHTS
      ↓
CHECK NETWORK
      ↓
CHECK YOUTUBE
      ↓
START
```

---

# 25. DOCKER

Provide production-quality Docker support.

Services should be independently deployable.

Suggested:

```text
api
worker
scheduler
agent-orchestrator
media-worker
stream-worker
postgres
redis
nginx
monitoring
```

Do not create unnecessary services.

Reuse existing STREMDBC infrastructure where appropriate.

---

# 26. DEVELOPMENT MODE

Provide a complete local development environment.

One command should start the platform.

Example:

```bash
docker compose up -d
```

Provide:

```text
.env.example
docker-compose.yml
database migrations
seed data
development configuration
```

---

# 27. TESTING

Implement:

## Unit tests

Agents:

```text
Music Director
Rights Validator
Scheduler
Metadata
Recovery
```

## Integration tests

Test:

```text
API → database
API → queue
worker → database
composition → FFmpeg
stream monitor → stream worker
```

## End-to-end test

Create a fake channel:

```text
music assets
visual assets
playlist
composition
FFmpeg
local RTMP server
monitoring
recovery
```

Do NOT require YouTube credentials for normal CI.

---

# 28. STREAM SIMULATOR

Build a local RTMP test target.

Example:

```text
STREMDBC
   ↓
FFmpeg
   ↓
Local RTMP Server
   ↓
Monitor
```

This allows CI to verify the streaming pipeline.

---

# 29. FAILURE TESTING

Explicitly test:

```text
FFmpeg crash
network disconnect
RTMP disconnect
invalid audio
missing video
missing track
rights failure
YouTube API failure
worker crash
database disconnect
Redis disconnect
disk full
CPU exhaustion
```

Verify recovery behavior.

---

# 30. DATABASE MIGRATIONS

Never modify production schema manually.

All schema changes must be migration-based.

Provide:

```text
migration up
migration down
migration status
```

---

# 31. CONFIGURATION

All environment-specific values must be configurable.

Never hard-code:

```text
passwords
API keys
OAuth credentials
RTMP secrets
JWT secrets
database credentials
```

Provide:

```text
.env.example
```

with safe placeholders.

---

# 32. RIGHTS-FIRST CONTENT PIPELINE

Mandatory pipeline:

```text
CONTENT IDEA
     ↓
ASSET SELECTION
     ↓
RIGHTS VALIDATION
     ↓
CONTENT VALIDATION
     ↓
COMPOSITION
     ↓
APPROVAL
     ↓
SCHEDULE
     ↓
STREAM
```

A failed rights check must block publication.

---

# 33. AI PROMPT ARCHITECTURE

Do not scatter prompts throughout application code.

Create:

```text
/prompts
    music_director
    music_producer
    visual_director
    metadata
    scheduler
    stream_engineer
    analytics
    optimizer
```

Version every prompt.

Example:

```text
music_director/v1
music_director/v2
```

Store:

```text
prompt_version
model
input
output
latency
token_usage
validation_status
```

---

# 34. MODEL ABSTRACTION

Do not hard-code one AI provider.

Create:

```text
AIProvider
```

with implementations such as:

```text
OpenAI
Gemini
local model
future providers
```

Agents should call the abstraction.

---

# 35. AGENT OUTPUT CONTRACT

Every agent must produce structured output.

Example:

```json
{
  "agent": "music_director",
  "version": "1.0",
  "status": "success",
  "plan": {},
  "warnings": [],
  "requires_approval": false
}
```

Validate against JSON Schema.

Reject malformed responses.

---

# 36. NO FAKE IMPLEMENTATION

Do not create placeholder functions that claim to work.

Avoid:

```python
pass
```

or:

```python
raise NotImplementedError
```

for required production functionality.

If a feature cannot yet be implemented:

1. document why
2. isolate it behind an interface
3. provide a working fallback where possible
4. add a tracked TODO
5. add tests for the boundary

---

# 37. REPOSITORY AUDIT FIRST

Before changing architecture:

1. inspect the entire repository
2. identify existing services
3. identify existing streaming code
4. identify database schema
5. identify APIs
6. identify workers
7. identify Docker configuration
8. identify tests
9. identify duplicated functionality
10. identify broken implementations

Do not blindly overwrite working STREMDBC components.

Prefer incremental refactoring.

---

# 38. CODE QUALITY

Follow the repository's existing language and framework conventions where practical.

Enforce:

- type safety
- linting
- formatting
- error handling
- structured logging
- configuration validation
- test coverage
- documentation

Remove dead code.

Remove duplicated code.

Do not introduce unnecessary dependencies.

---

# 39. SECURITY REVIEW

Perform a security review before completion.

Look specifically for:

```text
command injection
SSRF
path traversal
file upload vulnerabilities
credential leakage
API authorization bypass
privilege escalation
unsafe agent execution
secret exposure
unvalidated URLs
arbitrary FFmpeg input
resource exhaustion
```

---

# 40. PERFORMANCE

The system must support multiple channels.

Do not assume:

```text
1 channel = 1 server
```

Design worker capacity explicitly.

Example:

```text
Channel A → Worker 1
Channel B → Worker 2
Channel C → Worker 3
```

Support horizontal scaling.

---

# 41. DEPLOYMENT TARGET

Support:

```text
single-node Docker
```

first.

Then make architecture compatible with:

```text
Kubernetes
```

without requiring Kubernetes for development.

---

# 42. DOCUMENTATION

Create:

```text
README.md
ARCHITECTURE.md
AGENTS.md
API.md
STREAMING.md
YOUTUBE.md
CONTENT.md
RIGHTS.md
SECURITY.md
DEPLOYMENT.md
TROUBLESHOOTING.md
```

Include architecture diagrams using Mermaid where useful.

---

# 43. OPERATIONS COMMANDS

Provide commands for:

```bash
start
stop
restart
status
logs
health
migrate
seed
test
lint
build
worker
stream
```

Document every command.

---

# 44. ACCEPTANCE TEST

The implementation is NOT complete until this scenario works locally:

```text
CREATE CHANNEL
       ↓
CONFIGURE CHANNEL
       ↓
ADD LICENSED/OWNED MUSIC
       ↓
ADD VISUAL ASSET
       ↓
CREATE PLAYLIST
       ↓
RUN MUSIC DIRECTOR
       ↓
RUN RIGHTS VALIDATOR
       ↓
CREATE COMPOSITION
       ↓
GENERATE METADATA
       ↓
PREFLIGHT
       ↓
START STREAM
       ↓
FFMPEG ENCODE
       ↓
LOCAL RTMP
       ↓
MONITOR
       ↓
SIMULATE FAILURE
       ↓
RECOVERY
       ↓
STREAM CONTINUES
       ↓
STOP STREAM
       ↓
ANALYTICS REPORT
```

All major steps must be observable and testable.

---

# 45. IMPLEMENTATION ORDER

Execute in this order.

## PHASE 0 — AUDIT

Deeply inspect existing STREMDBC.

Produce:

```text
architecture map
dependency map
service map
database map
streaming map
test map
risk map
```

Do not modify code yet.

---

## PHASE 1 — FOUNDATION

Implement:

- configuration
- database models
- migrations
- API foundation
- job system
- event system
- authentication
- logging
- health checks

---

## PHASE 2 — MEDIA ENGINE

Implement:

- media assets
- playlists
- composition
- FFmpeg integration
- local RTMP
- stream lifecycle

---

## PHASE 3 — STREAM MONITORING

Implement:

- health monitoring
- metrics
- failure detection
- recovery
- resource monitoring

---

## PHASE 4 — CONTENT AGENTS

Implement:

- Music Director
- Music Production
- Rights Validator
- Visual Director
- Visual Asset
- Brand
- Content Composer
- Metadata

---

## PHASE 5 — SCHEDULING

Implement:

- scheduler
- recurring programming
- channel schedules
- timezone handling
- autonomous mode

---

## PHASE 6 — YOUTUBE

Implement:

- OAuth
- channel integration
- broadcast management
- stream management
- metadata synchronization

Use mocks in CI.

---

## PHASE 7 — ANALYTICS

Implement:

- event collection
- stream analytics
- reports
- optimization recommendations

---

## PHASE 8 — DASHBOARD

Implement the complete operator UI.

---

## PHASE 9 — HARDENING

Perform:

- security audit
- performance testing
- failure testing
- concurrency testing
- resource testing
- recovery testing

---

## PHASE 10 — PRODUCTION RELEASE

Produce:

```text
production Docker configuration
environment template
database migration
deployment documentation
backup procedure
rollback procedure
monitoring documentation
incident runbook
```

---

# 46. REQUIRED DELIVERABLE

At completion provide:

```text
1. Complete modified codebase
2. Database migrations
3. Docker configuration
4. Environment template
5. Agent implementations
6. Media pipeline
7. Streaming pipeline
8. Monitoring
9. Recovery
10. YouTube integration
11. Dashboard
12. Automated tests
13. Documentation
14. Security review
15. Production deployment instructions
```

---

# 47. FINAL ENGINEERING RULE

Do not optimize for the appearance of completeness.

Optimize for:

```text
CORRECTNESS
RELIABILITY
OBSERVABILITY
SECURITY
RECOVERABILITY
TESTABILITY
SCALABILITY
```

A feature is considered implemented only when:

```text
CODE
+
CONFIGURATION
+
VALIDATION
+
TEST
+
DOCUMENTATION
```

all exist.

---

# FINAL COMMAND

Start by performing a deep repository audit.

Do not immediately rewrite STREMDBC.

Identify what already works.

Preserve good components.

Refactor only where necessary.

Then implement the system phase-by-phase.

After every phase:

```text
RUN TESTS
↓
FIX FAILURES
↓
RUN LINT
↓
RUN BUILD
↓
RUN INTEGRATION TESTS
↓
DOCUMENT RESULT
```

Never report success based only on code generation.

The final system must be runnable.

The final system must have a working local end-to-end streaming path.

The final system must be capable of evolving from local RTMP testing into production YouTube Live broadcasting.

Build STREMDBC as an **AI-native broadcasting platform**, not merely a collection of AI agents.