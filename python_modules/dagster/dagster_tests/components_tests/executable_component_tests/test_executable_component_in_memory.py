import inspect
from textwrap import dedent

from dagster._core.definitions.asset_key import CoercibleToAssetKey
from dagster._core.definitions.asset_spec import AssetSpec
from dagster._core.definitions.assets import AssetsDefinition
from dagster._core.definitions.materialize import materialize
from dagster._core.definitions.metadata.metadata_value import TextMetadataValue
from dagster._core.definitions.resource_annotation import ResourceParam
from dagster._core.definitions.result import MaterializeResult
from dagster.components.core.context import ComponentLoadContext
from dagster.components.lib.executable_component.function_component import (
    FunctionComponent,
    FunctionSpec,
)
from dagster.components.testing import scaffold_defs_sandbox


def asset_in_component(component: FunctionComponent, key: CoercibleToAssetKey) -> AssetsDefinition:
    defs = component.build_defs(ComponentLoadContext.for_test())
    return defs.get_assets_def(key)


def test_include() -> None:
    assert FunctionComponent


def test_basic_singular_asset() -> None:
    def _execute_fn(context) -> MaterializeResult:
        return MaterializeResult(metadata={"foo": "bar"})

    component = FunctionComponent(
        execution=FunctionSpec(name="op_name", fn=_execute_fn),
        assets=[AssetSpec(key="asset")],
    )

    assert isinstance(component, FunctionComponent)
    assert_singular_component(component)


def test_basic_singular_asset_with_callable() -> None:
    def op_name(context) -> MaterializeResult:
        return MaterializeResult(metadata={"foo": "bar"})

    component = FunctionComponent(execution=op_name, assets=[AssetSpec(key="asset")])

    assert isinstance(component, FunctionComponent)
    assert_singular_component(component)


def assert_singular_component(component: FunctionComponent) -> None:
    defs = component.build_defs(ComponentLoadContext.for_test())

    assets_def = defs.get_assets_def("asset")

    assert assets_def.op.name == "op_name"
    assert assets_def.key.to_user_string() == "asset"

    result = materialize([assets_def])
    assert result.success
    mats = result.asset_materializations_for_node("op_name")
    assert len(mats) == 1
    assert mats[0].metadata == {"foo": TextMetadataValue("bar")}


def execute_singular_asset(context) -> MaterializeResult:
    return MaterializeResult(metadata={"foo": "bar"})


def op_name(context) -> MaterializeResult:
    return MaterializeResult(metadata={"foo": "bar"})


def test_basic_singular_asset_from_yaml() -> None:
    component = FunctionComponent.from_attributes_dict(
        attributes={
            "execution": {
                "name": "op_name",
                "fn": "dagster_tests.components_tests.executable_component_tests.test_executable_component_in_memory.execute_singular_asset",
            },
            "assets": [
                {
                    "key": "asset",
                }
            ],
        }
    )
    assert isinstance(component, FunctionComponent)
    assert_singular_component(component)


def test_basic_singular_asset_from_callable() -> None:
    component = FunctionComponent.from_attributes_dict(
        attributes={
            "execution": "dagster_tests.components_tests.executable_component_tests.test_executable_component_in_memory.op_name",
            "assets": [
                {
                    "key": "asset",
                }
            ],
        }
    )
    assert isinstance(component, FunctionComponent)
    assert_singular_component(component)


def test_resource_usage() -> None:
    def _execute_fn(context, some_resource: ResourceParam[str]) -> MaterializeResult:
        return MaterializeResult(metadata={"foo": some_resource})

    component = FunctionComponent(
        execution=FunctionSpec(name="op_name", fn=_execute_fn),
        assets=[AssetSpec(key="asset")],
    )

    assets_def = asset_in_component(component, "asset")

    result = materialize([assets_def], resources={"some_resource": "some_value"})
    assert result.success
    mats = result.asset_materializations_for_node("op_name")
    assert len(mats) == 1
    assert mats[0].metadata == {"foo": TextMetadataValue("some_value")}


def test_local_import() -> None:
    def execute_fn_to_copy(context):
        from dagster import MaterializeResult

        return MaterializeResult(metadata={"foo": "bar"})

    with scaffold_defs_sandbox(component_cls=FunctionComponent) as sandbox:
        execute_fn_content = inspect.getsource(execute_fn_to_copy)
        execute_path = sandbox.defs_folder_path / "execute.py"
        execute_path.write_text(dedent(execute_fn_content))

        with sandbox.load(
            component_body={
                "type": "dagster.components.lib.executable_component.function_component.FunctionComponent",
                "attributes": {
                    "execution": {
                        "name": "op_name",
                        "fn": ".execute.execute_fn_to_copy",
                    },
                    "assets": [
                        {
                            "key": "asset",
                        }
                    ],
                },
            }
        ) as (component, defs):
            assert isinstance(component, FunctionComponent)
            assert isinstance(component.execution, FunctionSpec)
            assert component.execution.fn.__name__ == "execute_fn_to_copy"
            assert isinstance(component.execution.fn(None), MaterializeResult)

            assets_def = defs.get_assets_def("asset")
            assert assets_def.op.name == "op_name"
            assert assets_def.key.to_user_string() == "asset"

            result = materialize([assets_def])
            assert result.success
            mats = result.asset_materializations_for_node("op_name")
            assert len(mats) == 1
            assert mats[0].metadata == {"foo": TextMetadataValue("bar")}
