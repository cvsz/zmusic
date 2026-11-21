"""Worker architecture tests for zMusic."""

import time
import unittest

from scripts.worker import (
    QUEUE_CONFIGS,
    Job,
    JobPriority,
    JobQueue,
    JobRegistry,
    JobStatus,
    Worker,
    WorkerConfig,
    WorkerPool,
    create_default_pools,
    get_job_registry,
)


class JobTest(unittest.TestCase):
    def test_job_creation(self):
        job = Job(
            job_id="job-001",
            job_type="test_job",
            payload={"key": "value"},
            priority=JobPriority.HIGH.value,
        )
        self.assertEqual(job.job_id, "job-001")
        self.assertEqual(job.job_type, "test_job")
        self.assertEqual(job.priority, JobPriority.HIGH.value)
        self.assertEqual(job.status, JobStatus.CREATED)

    def test_job_defaults(self):
        job = Job(job_id="job-001", job_type="test", payload={})
        self.assertEqual(job.attempt, 0)
        self.assertEqual(job.max_attempts, 3)
        self.assertIsNotNone(job.created_at)


class JobQueueTest(unittest.TestCase):
    def setUp(self):
        self.queue = JobQueue("test-queue")

    def test_enqueue_dequeue(self):
        job = Job(job_id="job-001", job_type="test", payload={})
        self.queue.enqueue(job)
        dequeued = self.queue.dequeue(timeout=0.5)
        self.assertIsNotNone(dequeued)
        self.assertEqual(dequeued.job_id, "job-001")

    def test_priority_ordering(self):
        # High priority should come first
        low_job = Job(
            job_id="low", job_type="test", payload={}, priority=JobPriority.LOW.value
        )
        high_job = Job(
            job_id="high", job_type="test", payload={}, priority=JobPriority.HIGH.value
        )

        self.queue.enqueue(low_job)
        self.queue.enqueue(high_job)

        first = self.queue.dequeue(timeout=0.5)
        self.assertEqual(first.job_id, "high")

        second = self.queue.dequeue(timeout=0.5)
        self.assertEqual(second.job_id, "low")

    def test_get_job(self):
        job = Job(job_id="job-001", job_type="test", payload={})
        self.queue.enqueue(job)
        retrieved = self.queue.get_job("job-001")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.job_id, "job-001")

    def test_update_job(self):
        job = Job(job_id="job-001", job_type="test", payload={})
        self.queue.enqueue(job)
        # Use with_status method for frozen dataclass
        updated_job = job.with_status(JobStatus.COMPLETED)
        self.queue.update_job(updated_job)
        retrieved = self.queue.get_job("job-001")
        self.assertEqual(retrieved.status, JobStatus.COMPLETED)

    def test_remove_job(self):
        job = Job(job_id="job-001", job_type="test", payload={})
        self.queue.enqueue(job)
        self.assertTrue(self.queue.remove_job("job-001"))
        self.assertIsNone(self.queue.get_job("job-001"))


class WorkerConfigTest(unittest.TestCase):
    def test_default_config(self):
        config = WorkerConfig("test-queue")
        self.assertEqual(config.queue_name, "test-queue")
        self.assertEqual(config.max_workers, 4)
        self.assertEqual(config.max_retries, 3)

    def test_custom_config(self):
        config = WorkerConfig(
            "custom-queue",
            max_workers=8,
            max_retries=5,
            base_retry_delay=2.0,
        )
        self.assertEqual(config.max_workers, 8)
        self.assertEqual(config.max_retries, 5)
        self.assertEqual(config.base_retry_delay, 2.0)


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.queue = JobQueue("test-queue")
        self.config = WorkerConfig("test-queue", max_workers=1, base_retry_delay=0.01)
        self.results = []

    def test_worker_starts_and_stops(self):
        def handler(job: Job):
            self.results.append(job.job_id)

        worker = Worker(self.queue, handler, self.config, "test-worker")
        worker.start()
        time.sleep(0.1)
        worker.stop()
        self.assertFalse(worker._running)

    def test_worker_processes_job(self):
        def handler(job: Job):
            self.results.append(job.job_id)

        worker = Worker(self.queue, handler, self.config, "test-worker")
        worker.start()

        job = Job(job_id="job-001", job_type="test", payload={})
        self.queue.enqueue(job)

        time.sleep(0.2)  # Wait for processing
        worker.stop()

        self.assertIn("job-001", self.results)


class WorkerPoolTest(unittest.TestCase):
    def setUp(self):
        self.config = WorkerConfig("test-pool", max_workers=2, base_retry_delay=0.01)
        self.results = []

    def test_pool_start_stop(self):
        def handler(job: Job):
            self.results.append(job.job_id)

        pool = WorkerPool(self.config, handler)
        pool.start()
        self.assertEqual(len(pool.workers), 2)
        pool.stop()
        self.assertTrue(all(not w._running for w in pool.workers))

    def test_submit_job(self):
        def handler(job: Job):
            self.results.append(job.job_id)

        pool = WorkerPool(self.config, handler)
        pool.start()

        job_id = pool.submit_job("test_type", {"data": "value"})
        self.assertIsNotNone(job_id)

        time.sleep(0.2)
        pool.stop()

        self.assertIn(job_id, self.results)

    def test_job_status_tracking(self):
        def handler(job: Job):
            pass

        pool = WorkerPool(self.config, handler)
        pool.start()

        job_id = pool.submit_job("test_type", {})
        job = pool.get_job_status(job_id)

        self.assertIsNotNone(job)
        self.assertEqual(job.job_id, job_id)
        self.assertEqual(job.job_type, "test_type")

    def test_queue_stats(self):
        def handler(job: Job):
            pass

        pool = WorkerPool(self.config, handler)
        pool.start()

        pool.submit_job("type1", {})
        pool.submit_job("type2", {})

        stats = pool.get_queue_stats()
        self.assertEqual(stats["queue_name"], "test-pool")
        self.assertEqual(stats["pending_count"], 2)
        self.assertEqual(stats["workers"], 2)

        pool.stop()


class JobRegistryTest(unittest.TestCase):
    def test_registry_singleton(self):
        reg1 = get_job_registry()
        reg2 = get_job_registry()
        self.assertIs(reg1, reg2)

    def test_register_pool(self):
        registry = JobRegistry()
        config = WorkerConfig("test-queue", max_workers=1)

        def handler(job: Job):
            pass

        pool = registry.register_pool(config, handler)
        self.assertIsNotNone(pool)
        self.assertEqual(pool.config.queue_name, "test-queue")

        # Duplicate should fail
        with self.assertRaises(ValueError):
            registry.register_pool(config, handler)

    def test_get_pool(self):
        registry = JobRegistry()
        config = WorkerConfig("test-queue", max_workers=1)

        def handler(job: Job):
            pass

        registry.register_pool(config, handler)
        pool = registry.get_pool("test-queue")
        self.assertIsNotNone(pool)

        # Non-existent
        self.assertIsNone(registry.get_pool("nonexistent"))

    def test_submit_job_via_registry(self):
        registry = JobRegistry()
        config = WorkerConfig("test-queue", max_workers=1)

        def handler(job: Job):
            pass

        registry.register_pool(config, handler)

        job_id = registry.submit_job("test-queue", "test_type", {"key": "value"})
        self.assertIsNotNone(job_id)

        # Non-existent queue
        result = registry.submit_job("nonexistent", "test", {})
        self.assertIsNone(result)

    def test_get_all_stats(self):
        registry = JobRegistry()
        config = WorkerConfig("test-queue", max_workers=1)

        def handler(job: Job):
            pass

        registry.register_pool(config, handler)

        stats = registry.get_all_stats()
        self.assertIn("test-queue", stats)
        self.assertEqual(stats["test-queue"]["queue_name"], "test-queue")


class DefaultPoolsTest(unittest.TestCase):
    def test_create_default_pools(self):
        registry = create_default_pools()

        # Should have all predefined queues
        for queue_name in QUEUE_CONFIGS:
            pool = registry.get_pool(queue_name)
            self.assertIsNotNone(pool, f"Missing pool for {queue_name}")
            self.assertEqual(pool.config.queue_name, queue_name)


if __name__ == "__main__":
    unittest.main()
