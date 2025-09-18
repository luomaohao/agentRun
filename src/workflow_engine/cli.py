"""
Agent Workflow Runtime CLI
"""
import click
import asyncio
import yaml
import json
from pathlib import Path

from .api.app import app
from .core import WorkflowEngine


@click.group()
def cli():
    """Agent Workflow Runtime CLI"""
    pass


@cli.command()
@click.option('--host', default='0.0.0.0', help='Host to bind to')
@click.option('--port', default=8000, help='Port to bind to')
@click.option('--reload', is_flag=True, help='Enable auto-reload')
def serve(host, port, reload):
    """Start the API server"""
    import uvicorn
    
    click.echo(f"Starting API server on {host}:{port}")
    uvicorn.run(
        "src.workflow_engine.api:app",
        host=host,
        port=port,
        reload=reload
    )


@cli.command()
@click.argument('workflow_file', type=click.Path(exists=True))
@click.option('--validate-only', is_flag=True, help='Only validate, do not execute')
def run(workflow_file, validate_only):
    """Run a workflow from file"""
    async def _run():
        # Load workflow
        with open(workflow_file, 'r') as f:
            if workflow_file.endswith('.yaml') or workflow_file.endswith('.yml'):
                workflow_def = yaml.safe_load(f)
            else:
                workflow_def = json.load(f)
        
        # Create engine
        from .storage.repository import InMemoryWorkflowRepository, InMemoryExecutionRepository
        from .integrations import EventBus, MockAgentRuntime, LocalToolRegistry
        
        engine = WorkflowEngine(
            workflow_repository=InMemoryWorkflowRepository(),
            execution_repository=InMemoryExecutionRepository(),
            event_bus=EventBus(),
            agent_runtime=MockAgentRuntime(),
            tool_registry=LocalToolRegistry()
        )
        
        # Create workflow
        workflow_id = await engine.create_workflow(workflow_def)
        click.echo(f"Created workflow: {workflow_id}")
        
        if not validate_only:
            # Execute workflow
            execution_id = await engine.execute_workflow(workflow_id)
            click.echo(f"Started execution: {execution_id}")
            
            # Wait for completion
            # TODO: Implement proper waiting and status reporting
    
    asyncio.run(_run())


@cli.command()
def init():
    """Initialize a new workflow project"""
    click.echo("Initializing new workflow project...")
    
    # Create directories
    dirs = ['workflows', 'agents', 'tools', 'configs']
    for dir_name in dirs:
        Path(dir_name).mkdir(exist_ok=True)
        click.echo(f"Created {dir_name}/")
    
    # Create example workflow
    example_workflow = {
        "workflow": {
            "name": "Example Workflow",
            "version": "1.0.0",
            "type": "dag",
            "nodes": [
                {
                    "id": "start",
                    "type": "agent",
                    "config": {"agent_id": "example-agent"},
                    "inputs": {"message": "${input.message}"}
                }
            ]
        }
    }
    
    with open('workflows/example.yaml', 'w') as f:
        yaml.dump(example_workflow, f)
    
    click.echo("Created workflows/example.yaml")
    click.echo("Project initialized successfully!")


def main():
    """Main entry point"""
    cli()


if __name__ == '__main__':
    main()
