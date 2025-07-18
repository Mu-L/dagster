import datetime

import dagster as dg
import pytest
from dagster import AutomationCondition, DagsterInstance
from dagster._core.definitions.partitions.definition import StaticPartitionsDefinition

from dagster_tests.declarative_automation_tests.scenario_utils.automation_condition_scenario import (
    AutomationConditionScenarioState,
)
from dagster_tests.declarative_automation_tests.scenario_utils.base_scenario import run_request
from dagster_tests.declarative_automation_tests.scenario_utils.scenario_specs import (
    hourly_partitions_def,
    two_assets_in_sequence,
)


@pytest.mark.asyncio
async def test_eager_unpartitioned() -> None:
    state = AutomationConditionScenarioState(
        two_assets_in_sequence,
        automation_condition=AutomationCondition.eager(),
        ensure_empty_result=False,
    )

    # parent hasn't updated yet
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 0

    # parent updated, now can execute
    state = state.with_runs(run_request("A"))
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 1

    # B has not yet materialized, but it has been requested, so don't request again
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 0

    # same as above
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 0

    # now B has been materialized, so really shouldn't execute again
    state = state.with_runs(
        *(
            run_request(ak, pk)
            for ak, pk in result.true_subset.expensively_compute_asset_partitions()
        )
    )
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 0

    # A gets materialized again before the hour, execute B again
    state = state.with_runs(run_request("A"))
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 1
    # however, B fails
    state = state.with_failed_run_for_asset("B")

    # do not try to materialize B again immediately
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 0

    evaluation = result.serializable_evaluation
    assert evaluation.condition_snapshot.operator_type == "and"


@pytest.mark.asyncio
async def test_eager_hourly_partitioned() -> None:
    state = (
        AutomationConditionScenarioState(
            two_assets_in_sequence,
            automation_condition=AutomationCondition.eager(),
            ensure_empty_result=False,
        )
        .with_asset_properties(partitions_def=hourly_partitions_def)
        .with_current_time("2020-02-02T01:05:00")
    )

    # parent hasn't updated yet
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 0

    # historical parent updated, doesn't matter
    state = state.with_runs(run_request("A", "2019-07-05-00:00"))
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 0

    # latest parent updated, now can execute
    state = state.with_runs(run_request("A", "2020-02-02-00:00"))
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 1
    state = state.with_runs(
        *(
            run_request(ak, pk)
            for ak, pk in result.true_subset.expensively_compute_asset_partitions()
        )
    )

    # now B has been materialized, so don't execute again
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 0

    # new partition comes into being, parent hasn't been materialized yet
    state = state.with_current_time_advanced(hours=1)
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 0

    # parent gets materialized, B requested
    state = state.with_runs(run_request("A", "2020-02-02-01:00"))
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 1
    # but it fails
    state = state.with_failed_run_for_asset("B", "2020-02-02-01:00")

    # B does not get immediately requested again
    state, result = await state.evaluate("B")
    assert result.true_subset.size == 0


def test_eager_static_partitioned() -> None:
    two_partitions = dg.StaticPartitionsDefinition(["a", "b"])
    four_partitions = dg.StaticPartitionsDefinition(["a", "b", "c", "d"])

    def _get_defs(pd: StaticPartitionsDefinition) -> dg.Definitions:
        @dg.asset(partitions_def=pd, automation_condition=AutomationCondition.eager())
        def A() -> None: ...

        @dg.asset(partitions_def=pd, automation_condition=AutomationCondition.eager())
        def B() -> None: ...

        return dg.Definitions(assets=[A, B])

    with dg.instance_for_test() as instance:
        # no "surprise backfill"
        result = dg.evaluate_automation_conditions(
            defs=_get_defs(two_partitions), instance=instance
        )
        assert result.total_requested == 0

        # now add two more partitions to the definition, kick off a run for those
        result = dg.evaluate_automation_conditions(
            defs=_get_defs(four_partitions), instance=instance, cursor=result.cursor
        )
        assert result.total_requested == 4
        assert result.get_requested_partitions(dg.AssetKey("A")) == {"c", "d"}
        assert result.get_requested_partitions(dg.AssetKey("B")) == {"c", "d"}

        # already requested, no more
        result = dg.evaluate_automation_conditions(
            defs=_get_defs(four_partitions), instance=instance, cursor=result.cursor
        )
        assert result.total_requested == 0


def test_eager_self_dependency() -> None:
    @dg.asset
    def root() -> None: ...

    @dg.asset(
        deps=[
            root,
            dg.AssetDep(
                "A", partition_mapping=dg.TimeWindowPartitionMapping(start_offset=-1, end_offset=-1)
            ),
        ],
        automation_condition=AutomationCondition.eager(),
        partitions_def=dg.DailyPartitionsDefinition("2024-01-01"),
    )
    def A() -> None: ...

    defs = dg.Definitions(assets=[root, A])
    instance = DagsterInstance.ephemeral()

    # parent doesn't exist
    evaluation_time = datetime.datetime(2024, 8, 16, 1, 1)
    result = dg.evaluate_automation_conditions(
        defs=defs, instance=instance, evaluation_time=evaluation_time
    )
    assert result.total_requested == 0

    # now previous partition of A exists, so request
    defs.resolve_implicit_global_asset_job_def().execute_in_process(
        instance=instance, asset_selection=[root.key, A.key], partition_key="2024-08-14"
    )
    result = dg.evaluate_automation_conditions(
        defs=defs, instance=instance, cursor=result.cursor, evaluation_time=evaluation_time
    )
    assert result.total_requested == 1

    # don't keep requesting
    result = dg.evaluate_automation_conditions(
        defs=defs, instance=instance, cursor=result.cursor, evaluation_time=evaluation_time
    )
    assert result.total_requested == 0

    # now materialize the previous partition again, kick off again
    defs.resolve_implicit_global_asset_job_def().execute_in_process(
        instance=instance, asset_selection=[A.key], partition_key="2024-08-14"
    )
    result = dg.evaluate_automation_conditions(
        defs=defs, instance=instance, cursor=result.cursor, evaluation_time=evaluation_time
    )
    assert result.total_requested == 1

    # don't keep requesting
    result = dg.evaluate_automation_conditions(
        defs=defs, instance=instance, cursor=result.cursor, evaluation_time=evaluation_time
    )
    assert result.total_requested == 0


def test_eager_multi_partitioned_self_dependency() -> None:
    pd = dg.MultiPartitionsDefinition(
        {
            "time": dg.DailyPartitionsDefinition(start_date="2024-08-01"),
            "static": dg.StaticPartitionsDefinition(["a", "b", "c"]),
        }
    )

    @dg.asset(partitions_def=pd)
    def parent() -> None: ...

    @dg.asset(
        deps=[
            parent,
            dg.AssetDep(
                "child",
                partition_mapping=dg.MultiPartitionMapping(
                    {
                        "time": dg.DimensionPartitionMapping(
                            "time", dg.TimeWindowPartitionMapping(start_offset=-1, end_offset=-1)
                        ),
                    }
                ),
            ),
        ],
        partitions_def=pd,
        automation_condition=AutomationCondition.eager().without(
            AutomationCondition.in_latest_time_window()
        ),
    )
    def child() -> None: ...

    defs = dg.Definitions(assets=[parent, child])

    with dg.instance_for_test() as instance:
        # nothing happening
        result = dg.evaluate_automation_conditions(defs=defs, instance=instance)
        assert result.total_requested == 0

        # materialize upstream
        instance.report_runless_asset_event(
            dg.AssetMaterialization("parent", partition="a|2024-08-16")
        )
        result = dg.evaluate_automation_conditions(
            defs=defs, instance=instance, cursor=result.cursor
        )
        # can't materialize downstream yet because previous partition of child is still missing
        assert result.total_requested == 0


def test_eager_on_asset_check() -> None:
    @dg.asset
    def A() -> None: ...

    @dg.asset_check(asset=A, automation_condition=AutomationCondition.eager())
    def foo_check() -> ...: ...

    defs = dg.Definitions(assets=[A], asset_checks=[foo_check])

    instance = DagsterInstance.ephemeral()

    # parent hasn't been updated yet
    result = dg.evaluate_automation_conditions(defs=defs, instance=instance)
    assert result.total_requested == 0

    # now A is updated, so request
    instance.report_runless_asset_event(dg.AssetMaterialization("A"))
    result = dg.evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 1

    # don't keep requesting
    result = dg.evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 0

    # A updated again, re-request
    instance.report_runless_asset_event(dg.AssetMaterialization("A"))
    result = dg.evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 1

    # don't keep requesting
    result = dg.evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 0


@pytest.mark.parametrize("b_result", ["skip", "fail", "materialize"])
def test_eager_partial_run(b_result: str) -> None:
    @dg.asset
    def root() -> None: ...

    @dg.asset(deps=[root], automation_condition=AutomationCondition.eager())
    def A() -> None: ...

    @dg.asset(deps=[A], output_required=False, automation_condition=AutomationCondition.eager())
    def B():
        if b_result == "skip":
            pass
        elif b_result == "materialize":
            yield dg.Output(1)
        else:
            return 1 / 0

    @dg.asset(deps=[B], automation_condition=AutomationCondition.eager())
    def C() -> None: ...

    defs = dg.Definitions(assets=[root, A, B, C])
    instance = DagsterInstance.ephemeral()

    # nothing updated yet
    result = dg.evaluate_automation_conditions(defs=defs, instance=instance)
    assert result.total_requested == 0

    # now root updated, so request a, b, and c
    instance.report_runless_asset_event(dg.AssetMaterialization("root"))
    result = dg.evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 3

    # don't keep requesting
    result = dg.evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 0

    # now simulate the above run, B / C will not be materialized
    defs.resolve_implicit_global_asset_job_def().execute_in_process(
        instance=instance, asset_selection=[A.key, B.key, C.key], raise_on_error=False
    )
    result = dg.evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    # A gets materialized, but this shouldn't kick off B and C
    assert result.total_requested == 0

    # A gets materialized on its own, do kick off B and C
    defs.resolve_implicit_global_asset_job_def().execute_in_process(
        instance=instance, asset_selection=[A.key]
    )
    result = dg.evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 2
