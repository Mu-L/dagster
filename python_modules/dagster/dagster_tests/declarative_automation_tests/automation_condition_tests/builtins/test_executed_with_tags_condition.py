import pytest
from dagster import (
    AssetMaterialization,
    AutomationCondition,
    DagsterInstance,
    Definitions,
    asset,
    evaluate_automation_conditions,
)


@pytest.mark.parametrize(
    "condition,expected_name",
    [
        (
            AutomationCondition.executed_with_tags(tag_keys={"foo"}),
            "executed_with_tags(tag_keys={foo})",
        ),
        (
            AutomationCondition.executed_with_tags(tag_values={"foo": "bar", "baz": "1"}),
            "executed_with_tags(tag_values={baz:1,foo:bar})",
        ),
        (
            AutomationCondition.executed_with_tags(
                tag_keys={"a", "b"}, tag_values={"foo": "bar", "baz": "1"}
            ),
            "executed_with_tags(tag_keys={a,b}, tag_values={baz:1,foo:bar})",
        ),
    ],
)
def test_name(condition: AutomationCondition, expected_name: str) -> None:
    assert condition.name == expected_name


def test_executed_with_tag_keys() -> None:
    @asset(
        automation_condition=AutomationCondition.newly_updated()
        & AutomationCondition.executed_with_tags(tag_keys={"target_tag"})
    )
    def A() -> None: ...

    defs = Definitions(assets=[A])
    instance = DagsterInstance.ephemeral()
    job = defs.resolve_implicit_global_asset_job_def()

    # hasn't newly updated
    result = evaluate_automation_conditions(defs=defs, instance=instance)
    assert result.total_requested == 0

    # now updates, no tags
    job.execute_in_process(instance=instance)
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 0

    # now updates via automation system
    job.execute_in_process(instance=instance, tags={"target_tag": "true"})
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 1

    # no longer newly updated
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 0

    # updates, but not via automation system
    instance.report_runless_asset_event(AssetMaterialization("A"))
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 0

    # updates via automation system
    job.execute_in_process(instance=instance, tags={"target_tag": "true"})
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 1

    # updates via automation system
    job.execute_in_process(
        instance=instance, tags={"target_tag": "true", "non_target_tag": "false"}
    )
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 1

    job.execute_in_process(instance=instance, tags={"non_target_tag": "false"})
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 0


def test_executed_with_tag_values() -> None:
    @asset(
        automation_condition=AutomationCondition.newly_updated()
        & AutomationCondition.executed_with_tags(tag_values={"target_tag": "a"})
    )
    def A() -> None: ...

    defs = Definitions(assets=[A])
    instance = DagsterInstance.ephemeral()
    job = defs.resolve_implicit_global_asset_job_def()

    # hasn't newly updated
    result = evaluate_automation_conditions(defs=defs, instance=instance)
    assert result.total_requested == 0

    # now updates, but it was a manual run
    job.execute_in_process(instance=instance)
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 0

    # now updates with tag, but wrong value
    job.execute_in_process(instance=instance, tags={"target_tag": "b"})
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 0

    # now updates with tag, correct value
    job.execute_in_process(instance=instance, tags={"target_tag": "a"})
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 1

    # no longer newly updated
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 0

    # updates, no run
    instance.report_runless_asset_event(AssetMaterialization("A"))
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 0

    # updates via automation system
    job.execute_in_process(instance=instance, tags={"target_tag": "a"})
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 1

    job.execute_in_process(instance=instance, tags={"target_tag": "a", "non_target_tag": "b"})
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 1

    job.execute_in_process(instance=instance, tags={"non_target_tag": "b"})
    result = evaluate_automation_conditions(defs=defs, instance=instance, cursor=result.cursor)
    assert result.total_requested == 0
