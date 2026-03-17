#!/usr/bin/env python
"""
Example: Using Aider's Multi-Agent System

This example demonstrates how to spawn multiple agents to work on
different parts of a codebase in parallel.
"""

import asyncio
import sys
sys.path.insert(0, '/home/openclaw/openclaw/aider')

from aider.agents.agent import SubAgent, AgentStatus, AgentResult
from aider.agents.registry import AgentRegistry


async def example_parallel_code_review():
    """
    Example: Spawn multiple agents to review different files in parallel.
    """
    print("=" * 60)
    print("Example: Parallel Code Review")
    print("=" * 60)
    print()
    
    # Create a registry for managing agents
    registry = AgentRegistry(max_concurrent=5)
    
    # Define the files to review
    files_to_review = [
        ("auth.py", "security issues"),
        ("models.py", "SQL injection vulnerabilities"),
        ("api.py", "input validation"),
        ("utils.py", "performance optimizations"),
    ]
    
    # Spawn agents for each file
    agents = []
    for i, (filename, focus) in enumerate(files_to_review, 1):
        agent = SubAgent(
            id=f"review_{i}",
            name=f"Review: {filename}",
            task=f"Review {filename} for {focus}. List any issues found.",
            model="claude-3-5-sonnet-20241022",
            files=[filename],
            status=AgentStatus.PENDING
        )
        await registry.register(agent)
        agents.append(agent)
        print(f"✓ Spawned agent {agent.id}: Review {filename}")
    
    print(f"\nTotal agents spawned: {len(agents)}")
    print()
    
    # Simulate agents completing their work
    print("Simulating agent work...")
    for i, agent in enumerate(agents):
        agent.status = AgentStatus.RUNNING
        agent.started_at = agent.created_at
        
        # Simulate some work
        await asyncio.sleep(0.1)
        
        # Mark as completed
        agent.status = AgentStatus.COMPLETED
        agent.result = AgentResult(
            success=True,
            output=f"Review of {agent.files[0]} complete. Found {i} issues.",
            files_modified=[],
            execution_time=2.5
        )
        agent.completed_at = agent.started_at + 2.5
        print(f"✓ Agent {agent.id} completed")
    
    # Collect results
    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)
    
    stats = await registry.get_stats()
    print(f"Total agents: {stats['total']}")
    print(f"Completed: {stats['completed']}")
    print(f"Pending: {stats['pending']}")
    print(f"Running: {stats['running']}")
    print()
    
    for agent in agents:
        result = agent.result
        print(f"Agent: {agent.name}")
        print(f"  Status: {agent.status.name}")
        print(f"  Execution time: {agent.execution_time:.2f}s")
        print(f"  Output: {result.output[:60]}..." if len(result.output) > 60 else f"  Output: {result.output}")
        print()


async def example_multi_model_workflow():
    """
    Example: Use different models for different tasks in a workflow.
    """
    print("=" * 60)
    print("Example: Multi-Model Workflow")
    print("=" * 60)
    print()
    
    registry = AgentRegistry(max_concurrent=3)
    
    # Step 1: Architecture planning with a reasoning model
    print("Step 1: Architecture planning with Kimi K2.5")
    architect = SubAgent(
        id="architect_1",
        name="System Architect",
        task="Design a scalable API for payment processing. Include rate limiting, idempotency keys, and webhook support.",
        model="kimi-k2.5",
        files=[],
        status=AgentStatus.PENDING
    )
    await registry.register(architect)
    
    # Simulate work
    architect.status = AgentStatus.RUNNING
    architect.started_at = architect.created_at
    await asyncio.sleep(0.2)
    architect.status = AgentStatus.COMPLETED
    architect.result = AgentResult(
        success=True,
        output="""
Payment API Design:
1. POST /v1/payments - Create payment (idempotent with Idempotency-Key header)
2. GET /v1/payments/{id} - Retrieve payment status
3. POST /v1/webhooks - Register webhook endpoints
4. Rate limiting: 100 req/min per API key
""",
        files_modified=["api_design.md"]
    )
    architect.completed_at = architect.started_at + 5.0
    print(f"✓ Architect agent completed ({architect.execution_time:.2f}s)")
    print()
    
    # Step 2: Implementation with a coding model
    print("Step 2: Implementation with Claude 3.5 Sonnet")
    implementation = SubAgent(
        id="impl_1",
        name="Implementation",
        task=f"Implement the payment API based on the design: {architect.result.output[:100]}...",
        model="claude-3-5-sonnet-20241022",
        files=["payment_api.py", "models.py"],
        status=AgentStatus.PENDING
    )
    await registry.register(implementation)
    
    # Simulate work
    implementation.status = AgentStatus.RUNNING
    implementation.started_at = implementation.created_at
    await asyncio.sleep(0.2)
    implementation.status = AgentStatus.COMPLETED
    implementation.result = AgentResult(
        success=True,
        output="Implemented payment API with all required features",
        files_modified=["payment_api.py", "models.py", "webhooks.py"]
    )
    implementation.completed_at = implementation.started_at + 10.0
    print(f"✓ Implementation agent completed ({implementation.execution_time:.2f}s)")
    print()
    
    # Step 3: Testing with a lightweight model
    print("Step 3: Test generation with GPT-4o-mini")
    testing = SubAgent(
        id="test_1",
        name="Test Generation",
        task="Write comprehensive unit tests for the payment API",
        model="gpt-4o-mini",
        files=["payment_api.py", "test_payment_api.py"],
        status=AgentStatus.PENDING
    )
    await registry.register(testing)
    
    # Simulate work
    testing.status = AgentStatus.RUNNING
    testing.started_at = testing.created_at
    await asyncio.sleep(0.2)
    testing.status = AgentStatus.COMPLETED
    testing.result = AgentResult(
        success=True,
        output="Generated 15 unit tests covering all API endpoints",
        files_modified=["test_payment_api.py"]
    )
    testing.completed_at = testing.started_at + 3.0
    print(f"✓ Testing agent completed ({testing.execution_time:.2f}s)")
    print()
    
    # Summary
    print("=" * 60)
    print("Workflow Summary")
    print("=" * 60)
    
    stats = await registry.get_stats()
    print(f"Total time: {sum(a.execution_time for a in [architect, implementation, testing]):.2f}s")
    print(f"Models used: Kimi K2.5, Claude 3.5 Sonnet, GPT-4o-mini")
    print(f"Files modified: {sum(len(a.result.files_modified) for a in [architect, implementation, testing])}")
    print()


async def example_agent_management():
    """
    Example: Managing agent lifecycle - cancel, wait, get results.
    """
    print("=" * 60)
    print("Example: Agent Management")
    print("=" * 60)
    print()
    
    registry = AgentRegistry(max_concurrent=5)
    
    # Spawn several agents
    print("Spawning agents...")
    for i in range(5):
        agent = SubAgent(
            id=f"task_{i}",
            name=f"Background Task {i}",
            task=f"Process background task {i}",
            status=AgentStatus.PENDING
        )
        await registry.register(agent)
        print(f"  ✓ Agent task_{i} spawned")
    
    # List all agents
    print("\nAll agents:")
    all_agents = await registry.list_agents()
    for agent in all_agents:
        print(f"  - {agent.id}: {agent.status.name}")
    
    # Mark some as running and completed
    print("\nUpdating statuses...")
    all_agents[0].status = AgentStatus.RUNNING
    all_agents[0].started_at = all_agents[0].created_at
    all_agents[1].status = AgentStatus.COMPLETED
    all_agents[1].result = AgentResult(success=True, output="Done")
    all_agents[2].status = AgentStatus.ERROR
    all_agents[2].error = "Something went wrong"
    
    # List active agents
    print("\nActive agents (pending or running):")
    active = await registry.list_active()
    for agent in active:
        print(f"  - {agent.id}: {agent.status.name}")
    
    # Get statistics
    print("\nStatistics:")
    stats = await registry.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Cancel remaining active agents
    print("\nCancelling active agents...")
    cancelled = await registry.cancel_all()
    print(f"  Cancelled: {cancelled}")
    
    # Final stats
    print("\nFinal statistics:")
    stats = await registry.get_stats()
    print(f"  Total: {stats['total']}")
    print(f"  Running: {stats['running']}")
    print(f"  Cancelled: {stats['cancelled']}")
    print()


async def main():
    """Run all examples."""
    await example_parallel_code_review()
    print("\n")
    await example_multi_model_workflow()
    print("\n")
    await example_agent_management()
    
    print("=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
