import shutil

from dagster._components import AssetsComponent, ComponentLoadContext
from dagster._core.definitions.decorators.asset_decorator import multi_asset
from dagster._core.definitions.definitions_class import Definitions
from dagster._core.execution.context.asset_execution_context import AssetExecutionContext
from dagster._core.pipes.subprocess import PipesSubprocessClient


class PythonScript(AssetsComponent):
    def build_defs(self, load_context: ComponentLoadContext) -> Definitions:
        @multi_asset(specs=self.specs, name=f"script_{self.path.stem}")
        def _asset(context: AssetExecutionContext, pipes_client: PipesSubprocessClient):
            cmd = [shutil.which("python"), self.path]
            return pipes_client.run(command=cmd, context=context).get_results()

        return Definitions(assets=[_asset], resources=load_context.resources)
