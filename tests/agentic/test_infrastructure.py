import unittest


from aider.agents.governor import MissionGovernor
from aider.context import ProjectContext


class TestAgentInfrastructure(unittest.TestCase):
    def test_project_context_file_tracking(self):
        root = "/tmp/aider_test"
        ctx = ProjectContext(root)

        ctx.add_file("src/main.py")
        ctx.add_file("docs/README.md", read_only=True)

        # Verify relative path conversion
        self.assertEqual(ctx.get_relative_path(f"{root}/src/main.py"), "src/main.py")

        # Verify file sets (using endswith to handle resolved absolute paths)
        self.assertTrue(any(f.endswith("src/main.py") for f in ctx.abs_fnames))
        self.assertTrue(any(f.endswith("docs/README.md") for f in ctx.abs_read_only_fnames))

    def test_mission_governor_limits(self):
        # Reset governor for test
        gov = MissionGovernor(max_cost=0.05, max_turns=3, max_depth=2)
        gov._initialized = True  # Force re-init if needed
        gov.stats.total_cost = 0
        gov.stats.total_turns = 0

        # Turn 1: OK
        self.assertTrue(gov.check_safety("agent1", depth=1))
        gov.record_turn(cost=0.02)

        # Turn 2: OK
        self.assertTrue(gov.check_safety("agent1", depth=1))
        gov.record_turn(cost=0.02)

        # Depth check: Fail at depth 3
        self.assertFalse(gov.check_safety("agent2", depth=3))

        # Cost check: Fail after next turn
        gov.record_turn(cost=0.02)  # Total 0.06
        self.assertFalse(gov.check_safety("agent1", depth=1))


if __name__ == "__main__":
    unittest.main()
