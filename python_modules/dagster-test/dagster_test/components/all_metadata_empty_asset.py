from dagster import Component, ComponentLoadContext
from dagster._core.definitions.decorators.asset_decorator import asset
from dagster._core.definitions.definitions_class import Definitions
from dagster._core.execution.context.asset_execution_context import AssetExecutionContext


class AllMetadataEmptyComponent(Component):
    """Summary."""

    def build_defs(self, context: ComponentLoadContext) -> Definitions:
        @asset
        def hardcoded_asset(context: AssetExecutionContext):
            return 1

        return Definitions(assets=[hardcoded_asset])
