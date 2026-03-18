"""
File-Locked Task Board - Addresses deficit from Claude Code Agent Teams

This module provides file-locked task claiming to prevent race conditions
when multiple agents compete for the same tasks.

Location: ~/.aider/tasks/{team}/
"""

import os
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class Task:
    """Represents a task in the task board."""
    id: str
    title: str
    description: str
    status: str = "pending"  # pending, in_progress, completed, failed
    owner: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """Create from dictionary."""
        return cls(**data)


class FileLockedTaskBoard:
    """
    File-locked task board for multi-agent coordination.

    Prevents race conditions when multiple agents try to claim the same task.
    Uses file locking (fcntl) to ensure atomic operations.
    """

    def __init__(self, team_name: str = "default", base_dir: Optional[str] = None):
        """
        Initialize task board.

        Args:
            team_name: Name of the team
            base_dir: Base directory for task storage (default: ~/.aider/tasks/)
        """
        self.team_name = team_name
        self.base_dir = Path(base_dir or os.path.expanduser("~/.aider/tasks"))
        self.team_dir = self.base_dir / team_name
        self.tasks_file = self.team_dir / "tasks.json"
        self.locks_dir = self.team_dir / "locks"

        # Create directories
        self.team_dir.mkdir(parents=True, exist_ok=True)
        self.locks_dir.mkdir(parents=True, exist_ok=True)

        # Initialize tasks file if not exists
        if not self.tasks_file.exists():
            self._save_tasks({})

    def _get_lock_file(self, task_id: str) -> Path:
        """Get lock file path for a task."""
        return self.locks_dir / f"{task_id}.lock"

    def _acquire_lock(self, task_id: str, timeout: float = 5.0) -> bool:
        """
        Acquire exclusive lock on a task.

        Args:
            task_id: Task ID to lock
            timeout: Maximum time to wait for lock

        Returns:
            True if lock acquired, False otherwise
        """
        lock_file = self._get_lock_file(task_id)
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                # Write lock info
                lock_info = {
                    "task_id": task_id,
                    "locked_at": time.time(),
                    "locked_by": os.getpid()
                }
                os.write(fd, json.dumps(lock_info).encode())
                os.close(fd)
                return True
            except FileExistsError:
                # Lock file exists, check if it's stale
                try:
                    with open(lock_file, 'r') as f:
                        lock_info = json.load(f)

                    # If lock is older than 60 seconds, consider it stale
                    if time.time() - lock_info.get("locked_at", 0) > 60:
                        os.unlink(lock_file)
                        continue
                except Exception:
                    pass

                time.sleep(0.1)

        return False

    def _release_lock(self, task_id: str):
        """Release lock on a task."""
        lock_file = self._get_lock_file(task_id)
        try:
            os.unlink(lock_file)
        except FileNotFoundError:
            pass

    def _load_tasks(self) -> Dict[str, Task]:
        """Load tasks from file."""
        try:
            with open(self.tasks_file, 'r') as f:
                data = json.load(f)
            return {task_id: Task.from_dict(task_data) for task_id, task_data in data.items()}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_tasks(self, tasks: Dict[str, Task]):
        """Save tasks to file."""
        data = {task_id: task.to_dict() for task_id, task in tasks.items()}
        with open(self.tasks_file, 'w') as f:
            json.dump(data, f, indent=2)

    def create_task(
        self,
        task_id: str,
        title: str,
        description: str,
        dependencies: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Task:
        """
        Create a new task.

        Args:
            task_id: Unique task ID
            title: Task title
            description: Task description
            dependencies: List of task IDs this task depends on
            metadata: Additional metadata

        Returns:
            Created task
        """
        tasks = self._load_tasks()

        if task_id in tasks:
            raise ValueError(f"Task {task_id} already exists")

        task = Task(
            id=task_id,
            title=title,
            description=description,
            dependencies=dependencies or [],
            metadata=metadata or {}
        )

        tasks[task_id] = task
        self._save_tasks(tasks)

        logger.info(f"Created task: {task_id}")
        return task

    def claim_task(self, task_id: str, owner: str, timeout: float = 5.0) -> Optional[Task]:
        """
        Claim a task with file locking.

        Args:
            task_id: Task ID to claim
            owner: Agent claiming the task
            timeout: Maximum time to wait for lock

        Returns:
            Task if claimed successfully, None otherwise
        """
        # Acquire lock
        if not self._acquire_lock(task_id, timeout):
            logger.warning(f"Failed to acquire lock for task {task_id}")
            return None

        try:
            tasks = self._load_tasks()

            if task_id not in tasks:
                logger.error(f"Task {task_id} not found")
                return None

            task = tasks[task_id]

            # Check if already claimed
            if task.status != "pending":
                logger.warning(f"Task {task_id} is already {task.status}")
                return None

            # Check dependencies
            for dep_id in task.dependencies:
                if dep_id in tasks:
                    dep_task = tasks[dep_id]
                    if dep_task.status != "completed":
                        logger.warning(f"Task {task_id} depends on incomplete task {dep_id}")
                        return None

            # Claim the task
            task.status = "in_progress"
            task.owner = owner
            task.started_at = time.time()

            tasks[task_id] = task
            self._save_tasks(tasks)

            logger.info(f"Task {task_id} claimed by {owner}")
            return task

        finally:
            # Release lock
            self._release_lock(task_id)

    def complete_task(self, task_id: str, owner: str, success: bool = True) -> Optional[Task]:
        """
        Mark a task as completed.

        Args:
            task_id: Task ID to complete
            owner: Agent completing the task
            success: Whether the task was successful

        Returns:
            Updated task, or None if not found
        """
        tasks = self._load_tasks()

        if task_id not in tasks:
            logger.error(f"Task {task_id} not found")
            return None

        task = tasks[task_id]

        if task.owner != owner:
            logger.warning(f"Task {task_id} is owned by {task.owner}, not {owner}")
            return None

        task.status = "completed" if success else "failed"
        task.completed_at = time.time()

        tasks[task_id] = task
        self._save_tasks(tasks)

        logger.info(f"Task {task_id} completed by {owner}")
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        tasks = self._load_tasks()
        return tasks.get(task_id)

    def list_tasks(self, status: Optional[str] = None) -> List[Task]:
        """
        List all tasks, optionally filtered by status.

        Args:
            status: Filter by status (pending, in_progress, completed, failed)

        Returns:
            List of tasks
        """
        tasks = self._load_tasks()
        task_list = list(tasks.values())

        if status:
            task_list = [t for t in task_list if t.status == status]

        return task_list

    def get_available_tasks(self, owner: Optional[str] = None) -> List[Task]:
        """
        Get tasks that are available for claiming.

        Args:
            owner: Optional owner filter

        Returns:
            List of available tasks
        """
        tasks = self._load_tasks()
        available = []

        for task in tasks.values():
            # Must be pending
            if task.status != "pending":
                continue

            # All dependencies must be completed
            deps_complete = all(
                tasks.get(dep_id, Task("", "", "")).status == "completed"
                for dep_id in task.dependencies
            )

            if not deps_complete:
                continue

            available.append(task)

        return available

    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """
        Get the dependency graph.

        Returns:
            Dictionary mapping task IDs to their dependencies
        """
        tasks = self._load_tasks()
        return {
            task_id: task.dependencies
            for task_id, task in tasks.items()
        }

    def get_execution_order(self) -> List[List[str]]:
        """
        Get the execution order based on dependencies.

        Returns:
            List of lists, where each inner list contains tasks that can be executed in parallel
        """
        tasks = self._load_tasks()
        graph = self.get_dependency_graph()

        # Kahn's algorithm for topological sort
        in_degree = {task_id: 0 for task_id in tasks}
        for task_id, deps in graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[task_id] += 1

        # Find all tasks with no dependencies
        queue = [task_id for task_id, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            # All tasks in current level can be executed in parallel
            result.append(queue.copy())

            next_level = []
            for task_id in queue:
                # Find tasks that depend on this one
                for other_id, deps in graph.items():
                    if task_id in deps:
                        in_degree[other_id] -= 1
                        if in_degree[other_id] == 0:
                            next_level.append(other_id)

            queue = next_level

        return result

    def clear_completed_tasks(self, max_age_hours: float = 24.0):
        """
        Clear completed tasks older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours
        """
        tasks = self._load_tasks()
        cutoff = time.time() - (max_age_hours * 3600)

        to_remove = [
            task_id
            for task_id, task in tasks.items()
            if (
                task.status in ["completed", "failed"]
                and task.completed_at
                and task.completed_at < cutoff
            )
        ]

        for task_id in to_remove:
            del tasks[task_id]
            logger.info(f"Removed old task: {task_id}")

        self._save_tasks(tasks)

    def get_stats(self) -> Dict[str, int]:
        """Get task statistics."""
        tasks = self._load_tasks()

        stats = {
            "total": len(tasks),
            "pending": 0,
            "in_progress": 0,
            "completed": 0,
            "failed": 0
        }

        for task in tasks.values():
            stats[task.status] += 1

        return stats


# Integration with ArchitectCoder
class TaskBoardIntegration:
    """Integration helper for using task board with ArchitectCoder."""

    def __init__(self, team_name: str = "architect-team"):
        self.board = FileLockedTaskBoard(team_name)

    def create_architect_tasks(self, plan: str, tasks_data: List[Dict[str, Any]]):
        """
        Create tasks from an architect plan.

        Args:
            plan: The architect's plan
            tasks_data: List of task data from the plan
        """
        for task_data in tasks_data:
            self.board.create_task(
                task_id=task_data["id"],
                title=task_data["title"],
                description=task_data["description"],
                dependencies=task_data.get("dependencies", []),
                metadata={"plan": plan}
            )

    def claim_for_agent(self, agent_name: str) -> Optional[Task]:
        """
        Claim an available task for an agent.

        Args:
            agent_name: Name of the agent

        Returns:
            Claimed task, or None if no tasks available
        """
        available = self.board.get_available_tasks()

        if not available:
            return None

        # Claim first available task
        task = available[0]
        return self.board.claim_task(task.id, agent_name)

    def complete_for_agent(self, task_id: str, agent_name: str, success: bool = True):
        """Mark a task as completed for an agent."""
        return self.board.complete_task(task_id, agent_name, success)


if __name__ == "__main__":
    # Demo usage
    board = FileLockedTaskBoard("demo-team")

    # Create tasks
    board.create_task(
        "task-1",
        "Setup Database",
        "Create database schema and migrations",
        dependencies=[]
    )

    board.create_task(
        "task-2",
        "Create API",
        "Implement REST API endpoints",
        dependencies=["task-1"]
    )

    board.create_task(
        "task-3",
        "Build Frontend",
        "Create React components",
        dependencies=["task-2"]
    )

    # Get execution order
    order = board.get_execution_order()
    print("Execution order (parallel groups):")
    for i, group in enumerate(order):
        print(f"  Level {i}: {group}")

    # Claim and complete tasks
    task = board.claim_task("task-1", "db-agent")
    print(f"\nClaimed: {task.title}")

    board.complete_task("task-1", "db-agent")
    print("Completed: task-1")

    # Get stats
    stats = board.get_stats()
    print(f"\nStats: {stats}")
