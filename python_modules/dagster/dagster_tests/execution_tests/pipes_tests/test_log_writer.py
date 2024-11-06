import shutil
from typing import Iterator

import pytest
from dagster import AssetExecutionContext, DagsterInstance, asset, materialize
from dagster._core.pipes.subprocess import PipesSubprocessClient
from dagster._core.pipes.utils import PipesTempFileMessageReader

from dagster_tests.execution_tests.pipes_tests.utils import temp_script

_PYTHON_EXECUTABLE = shutil.which("python")


@pytest.fixture
def external_script_default_log_writer() -> Iterator[str]:
    # This is called in an external process and so cannot access outer scope
    def script_fn():
        import sys

        from dagster_pipes import open_dagster_pipes

        with open_dagster_pipes():
            sys.stdout.write("Writing this to stdout")
            sys.stderr.write("And this to stderr")

    with temp_script(script_fn) as script_path:
        yield script_path


def test_pipes_default_log_writer(
    tmpdir,
    capsys,
    external_script_default_log_writer,
):
    message_reader = PipesTempFileMessageReader(
        include_stdio_in_messages=True,
    )

    @asset
    def foo(context: AssetExecutionContext, ext: PipesSubprocessClient):
        cmd = [_PYTHON_EXECUTABLE, external_script_default_log_writer]
        return ext.run(
            command=cmd,
            context=context,
        ).get_results()

    resource = PipesSubprocessClient(message_reader=message_reader, forward_stdio=False)

    with DagsterInstance.ephemeral() as instance:
        result = materialize(
            [foo], instance=instance, resources={"ext": resource}, raise_on_error=False
        )

    captured = capsys.readouterr()
    stdout, stderr = captured.out, captured.err

    assert result.success

    assert "Writing this to stdout" in stdout
    assert "Starting PipesDefaultLogWriterChannel(stdout)" in stdout

    assert "Starting PipesDefaultLogWriterChannel(stderr)" in stderr
    assert "And this to stderr" in stderr
