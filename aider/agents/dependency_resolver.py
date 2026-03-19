"""
Automatic Dependency Resolution - Addresses deficit from Claude Code Agent Teams

This module provides automatic dependency analysis and graph building from plans.
Enables agents to understand task dependencies and execute in correct order.
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class DependencyNode:
    """Represents a node in the dependency graph."""

    task_id: str
    description: str
    dependencies: List[str]
    dependents: List[str]
    level: int = 0


class DependencyAnalyzer:
    """
    Analyzes plans and extracts task dependencies automatically.

    Uses natural language processing and heuristics to identify:
    - Task boundaries
    - Dependency relationships
    - Execution order
    """

    def __init__(self):
        # Keywords that indicate dependencies
        self.dependency_keywords = [
            "depends on",
            "requires",
            "needs",
            "after",
            "once",
            "when",
            "blocked by",
            "waiting for",
            "must complete first",
            "prerequisite",
        ]

        # Task boundary patterns
        self.task_patterns = [
            r"^\d+\.\s+(.+)$",  # Numbered lists
            r"^[-*]\s+(.+)$",  # Bullet lists
            r"^(.+?):\s+(.+)$",  # Key-value pairs
        ]

    def analyze_plan(self, plan: str) -> Dict[str, DependencyNode]:
        """
        Analyze a plan and extract dependency graph.

        Args:
            plan: The plan text to analyze

        Returns:
            Dictionary mapping task IDs to dependency nodes
        """
        # Extract tasks
        tasks = self._extract_tasks(plan)

        # Build dependency graph
        graph = self._build_dependency_graph(tasks)

        # Calculate levels (parallel execution groups)
        self._calculate_levels(graph)

        return graph

    def _extract_tasks(self, plan: str) -> Dict[str, Dict]:
        """
        Extract tasks from plan text.

        Args:
            plan: Plan text

        Returns:
            Dictionary of task_id -> task_info
        """
        tasks = {}
        lines = plan.split("\n")
        current_task_id = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Try each pattern
            for pattern in self.task_patterns:
                match = re.match(pattern, line)
                if match:
                    current_task_id += 1
                    task_id = f"task-{current_task_id}"

                    if len(match.groups()) == 2:
                        # Key-value pattern
                        title = match.group(1)
                        description = match.group(2)
                    else:
                        # List pattern
                        title = match.group(1)
                        description = title

                    tasks[task_id] = {
                        "title": title,
                        "description": description,
                        "dependencies": [],
                    }
                    break

        return tasks

    def _build_dependency_graph(self, tasks: Dict[str, Dict]) -> Dict[str, DependencyNode]:
        """
        Build dependency graph from tasks.

        Args:
            tasks: Dictionary of tasks

        Returns:
            Dictionary of dependency nodes
        """
        graph = {}

        # Create nodes
        for task_id, task_info in tasks.items():
            graph[task_id] = DependencyNode(
                task_id=task_id,
                description=task_info["description"],
                dependencies=[],
                dependents=[],
            )

        # Find dependencies
        for task_id, task_info in tasks.items():
            description = task_info["description"].lower()

            # Look for dependency keywords
            for keyword in self.dependency_keywords:
                if keyword in description:
                    # Try to extract referenced task
                    referenced = self._find_referenced_task(description, tasks)
                    if referenced and referenced != task_id:
                        graph[task_id].dependencies.append(referenced)
                        graph[referenced].dependents.append(task_id)

        return graph

    def _find_referenced_task(self, description: str, tasks: Dict[str, Dict]) -> Optional[str]:
        """
        Find a referenced task in description.

        Args:
            description: Task description
            tasks: Dictionary of tasks

        Returns:
            Referenced task ID, or None
        """
        description_lower = description.lower()

        # Look for task titles in description
        for task_id, task_info in tasks.items():
            title_words = task_info["title"].lower().split()
            if len(title_words) >= 2:
                # Check if at least 2 words from title appear in description
                matches = sum(1 for word in title_words if word in description_lower)
                if matches >= min(2, len(title_words)):
                    return task_id

        return None

    def _calculate_levels(self, graph: Dict[str, DependencyNode]):
        """
        Calculate levels for parallel execution.

        Args:
            graph: Dependency graph
        """
        # Kahn's algorithm for topological sort with level calculation
        in_degree = {task_id: len(node.dependencies) for task_id, node in graph.items()}

        # Level 0: tasks with no dependencies
        current_level = [task_id for task_id, degree in in_degree.items() if degree == 0]

        for task_id in current_level:
            graph[task_id].level = 0

        # BFS to calculate levels
        visited = set(current_level)
        queue = current_level.copy()

        while queue:
            task_id = queue.pop(0)
            node = graph[task_id]

            for dependent_id in node.dependents:
                if dependent_id not in visited:
                    # Update level
                    dependent_node = graph[dependent_id]
                    dependent_node.level = max(dependent_node.level, node.level + 1)

                    in_degree[dependent_id] -= 1
                    if in_degree[dependent_id] == 0:
                        visited.add(dependent_id)
                        queue.append(dependent_id)

    def get_execution_order(self, graph: Dict[str, DependencyNode]) -> List[List[str]]:
        """
        Get execution order as parallel groups.

        Args:
            graph: Dependency graph

        Returns:
            List of lists, where each inner list contains tasks that can be executed in parallel
        """
        # Group by level
        levels = {}
        for task_id, node in graph.items():
            if node.level not in levels:
                levels[node.level] = []
            levels[node.level].append(task_id)

        # Sort by level and return
        max_level = max(levels.keys()) if levels else -1
        return [levels.get(i, []) for i in range(max_level + 1)]

    def get_critical_path(self, graph: Dict[str, DependencyNode]) -> List[str]:
        """
        Get the critical path through the dependency graph.

        Args:
            graph: Dependency graph

        Returns:
            List of task IDs on the critical path
        """
        if not graph:
            return []

        # Find tasks with no dependents (end points)
        end_points = [task_id for task_id, node in graph.items() if not node.dependents]

        if not end_points:
            return []

        # Find longest path to any end point
        def longest_path(task_id: str, visited: Set[str]) -> List[str]:
            if task_id in visited:
                return []

            visited.add(task_id)
            node = graph[task_id]

            if not node.dependencies:
                return [task_id]

            max_path = []
            for dep_id in node.dependencies:
                path = longest_path(dep_id, visited.copy())
                if len(path) > len(max_path):
                    max_path = path

            return max_path + [task_id]

        # Find longest path
        critical_path = []
        for end_id in end_points:
            path = longest_path(end_id, set())
            if len(path) > len(critical_path):
                critical_path = path

        return critical_path

    def validate_graph(self, graph: Dict[str, DependencyNode]) -> Tuple[bool, List[str]]:
        """
        Validate dependency graph for cycles.

        Args:
            graph: Dependency graph

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []

        # Check for cycles using DFS
        def has_cycle(task_id: str, visited: Set[str], rec_stack: Set[str]) -> bool:
            visited.add(task_id)
            rec_stack.add(task_id)

            node = graph.get(task_id)
            if node:
                for dep_id in node.dependencies:
                    if dep_id not in visited:
                        if has_cycle(dep_id, visited, rec_stack):
                            return True
                    elif dep_id in rec_stack:
                        errors.append(f"Cycle detected: {task_id} -> {dep_id}")
                        return True

            rec_stack.remove(task_id)
            return False

        visited = set()
        for task_id in graph:
            if task_id not in visited:
                if has_cycle(task_id, visited, set()):
                    return False, errors

        # Check for missing dependencies
        for task_id, node in graph.items():
            for dep_id in node.dependencies:
                if dep_id not in graph:
                    errors.append(f"Missing dependency: {task_id} depends on non-existent {dep_id}")

        return len(errors) == 0, errors


# Integration with ArchitectCoder
class DependencyResolutionIntegration:
    """Integration helper for using dependency resolution with ArchitectCoder."""

    def __init__(self):
        self.analyzer = DependencyAnalyzer()

    def analyze_architect_plan(self, plan: str) -> Dict[str, any]:
        """
        Analyze an architect plan and return structured information.

        Args:
            plan: The architect's plan

        Returns:
            Dictionary with graph, execution order, and critical path
        """
        # Analyze plan
        graph = self.analyzer.analyze_plan(plan)

        # Validate
        is_valid, errors = self.analyzer.validate_graph(graph)

        if not is_valid:
            logger.warning(f"Dependency graph has issues: {errors}")

        # Get execution order
        execution_order = self.analyzer.get_execution_order(graph)

        # Get critical path
        critical_path = self.analyzer.get_critical_path(graph)

        return {
            "graph": graph,
            "execution_order": execution_order,
            "critical_path": critical_path,
            "is_valid": is_valid,
            "errors": errors,
        }

    def get_parallel_tasks(self, plan: str) -> List[List[str]]:
        """
        Get tasks that can be executed in parallel.

        Args:
            plan: The architect's plan

        Returns:
            List of lists of task IDs that can run in parallel
        """
        result = self.analyze_architect_plan(plan)
        return result["execution_order"]

    def get_next_tasks(self, plan: str, completed_tasks: List[str]) -> List[str]:
        """
        Get the next tasks that can be executed.

        Args:
            plan: The architect's plan
            completed_tasks: List of completed task IDs

        Returns:
            List of task IDs that are ready to execute
        """
        result = self.analyze_architect_plan(plan)
        graph = result["graph"]

        ready = []
        for task_id, node in graph.items():
            # Skip if already completed
            if task_id in completed_tasks:
                continue

            # Check if all dependencies are completed
            if all(dep_id in completed_tasks for dep_id in node.dependencies):
                ready.append(task_id)

        return ready


if __name__ == "__main__":
    # Demo usage
    plan = """
    1. Setup database schema
    2. Create API endpoints (depends on database schema)
    3. Build React components (depends on API endpoints)
    4. Add authentication (depends on database schema)
    5. Write integration tests (depends on API endpoints and React components)
    """

    analyzer = DependencyAnalyzer()
    graph = analyzer.analyze_plan(plan)

    print("Dependency Graph:")
    for task_id, node in graph.items():
        print(f"  {task_id}: {node.description}")
        if node.dependencies:
            print(f"    Dependencies: {node.dependencies}")
        if node.dependents:
            print(f"    Dependents: {node.dependents}")
        print(f"    Level: {node.level}")

    print("\nExecution Order (Parallel Groups):")
    execution_order = analyzer.get_execution_order(graph)
    for i, group in enumerate(execution_order):
        print(f"  Level {i}: {group}")

    print("\nCritical Path:")
    critical_path = analyzer.get_critical_path(graph)
    print(f"  {' -> '.join(critical_path)}")

    # Validate
    is_valid, errors = analyzer.validate_graph(graph)
    print(f"\nValid: {is_valid}")
    if errors:
        for error in errors:
            print(f"  Error: {error}")
