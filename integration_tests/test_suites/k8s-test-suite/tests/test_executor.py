import datetime
import os
import time
from collections.abc import Mapping
from typing import Any

import dagster._check as check
import kubernetes
import pytest
from dagster._core.events import DagsterEventType
from dagster._core.instance import DagsterInstance
from dagster._core.storage.dagster_run import DagsterRunStatus
from dagster._core.storage.tags import DOCKER_IMAGE_TAG
from dagster._utils.merger import merge_dicts
from dagster_k8s.client import DagsterKubernetesClient
from dagster_k8s.job import get_k8s_job_name
from dagster_k8s.test import wait_for_job_and_get_raw_logs
from dagster_k8s_test_infra.helm import (
    TEST_CONFIGMAP_NAME,
    TEST_IMAGE_PULL_SECRET_NAME,
    TEST_OTHER_CONFIGMAP_NAME,
    TEST_OTHER_IMAGE_PULL_SECRET_NAME,
    TEST_OTHER_SECRET_NAME,
    TEST_SECRET_NAME,
)
from dagster_k8s_test_infra.integration_utils import (
    can_terminate_run_over_graphql,
    image_pull_policy,
    launch_run_over_graphql,
    terminate_run_over_graphql,
)
from dagster_shared.yaml_utils import load_yaml_from_path
from dagster_test.test_project import (
    get_test_project_docker_image,
    get_test_project_environments_path,
)


@pytest.mark.integration
def test_k8s_run_launcher_no_celery_pods(system_namespace_for_k8s_run_launcher):
    pods = DagsterKubernetesClient.production_client().core_api.list_namespaced_pod(
        namespace=system_namespace_for_k8s_run_launcher
    )
    celery_pod_names = [p.metadata.name for p in pods.items if "celery-workers" in p.metadata.name]
    check.invariant(not celery_pod_names)


@pytest.mark.integration
def test_k8s_run_launcher_default(
    dagster_instance_for_k8s_run_launcher,
    user_code_namespace_for_k8s_run_launcher,
    dagster_docker_image,
    webserver_url_for_k8s_run_launcher,
):
    run_config = merge_dicts(
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env.yaml")),  # pyright: ignore[reportArgumentType]
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env_s3.yaml")),  # pyright: ignore[reportArgumentType]
        {
            "execution": {
                "config": {
                    "job_namespace": user_code_namespace_for_k8s_run_launcher,
                    "job_image": dagster_docker_image,
                    "image_pull_policy": image_pull_policy(),
                }
            },
        },
    )
    _launch_executor_run(
        webserver_url_for_k8s_run_launcher,
        run_config,
        dagster_instance_for_k8s_run_launcher,
        user_code_namespace_for_k8s_run_launcher,
    )


@pytest.mark.integration
def test_k8s_run_launcher_volume_mounts(
    dagster_instance_for_k8s_run_launcher,
    user_code_namespace_for_k8s_run_launcher,
    dagster_docker_image,
    webserver_url_for_k8s_run_launcher,
):
    run_config = merge_dicts(
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env_s3.yaml")),  # pyright: ignore[reportArgumentType]
        {
            "execution": {
                "config": {
                    "job_namespace": user_code_namespace_for_k8s_run_launcher,
                    "job_image": dagster_docker_image,
                    "image_pull_policy": image_pull_policy(),
                }
            },
        },
    )
    _launch_executor_run(
        webserver_url_for_k8s_run_launcher,
        run_config,
        dagster_instance_for_k8s_run_launcher,
        user_code_namespace_for_k8s_run_launcher,
        job_name="volume_mount_job_k8s",
        num_steps=1,
    )


@pytest.mark.integration
def test_k8s_executor_get_config_from_run_launcher(
    dagster_instance_for_k8s_run_launcher,
    user_code_namespace_for_k8s_run_launcher,
    dagster_docker_image,
    webserver_url_for_k8s_run_launcher,
):
    # Verify that if you do not specify executor config it is delegated by the run launcher
    run_config = merge_dicts(
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env.yaml")),  # pyright: ignore[reportArgumentType]
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env_s3.yaml")),  # pyright: ignore[reportArgumentType]
        {
            "execution": {"config": {"job_image": dagster_docker_image}},
        },
    )
    _launch_executor_run(
        webserver_url_for_k8s_run_launcher,
        run_config,
        dagster_instance_for_k8s_run_launcher,
        user_code_namespace_for_k8s_run_launcher,
    )


@pytest.mark.integration
def test_k8s_executor_combine_configs(
    dagster_instance_for_k8s_run_launcher,
    user_code_namespace_for_k8s_run_launcher,
    dagster_docker_image,
    webserver_url_for_k8s_run_launcher,
):
    # Verifies that the step pods created by the k8s executor combine secrets
    # from run launcher config and executor config. Also includes each executor secret
    # twice to verify that duplicates within the combined config are acceptable
    run_config = merge_dicts(
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env.yaml")),  # pyright: ignore[reportArgumentType]
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env_s3.yaml")),  # pyright: ignore[reportArgumentType]
        {
            "execution": {
                "config": {
                    "job_image": dagster_docker_image,
                    "image_pull_secrets": [
                        {"name": TEST_OTHER_IMAGE_PULL_SECRET_NAME},
                        {"name": TEST_OTHER_IMAGE_PULL_SECRET_NAME},
                    ],
                    "env_config_maps": [TEST_OTHER_CONFIGMAP_NAME, TEST_OTHER_CONFIGMAP_NAME],
                    "env_secrets": [TEST_OTHER_SECRET_NAME, TEST_OTHER_SECRET_NAME],
                    "labels": {"executor_label_key": "executor_label_value"},
                }
            },
        },
    )
    run_id = _launch_executor_run(
        webserver_url_for_k8s_run_launcher,
        run_config,
        dagster_instance_for_k8s_run_launcher,
        user_code_namespace_for_k8s_run_launcher,
    )

    step_job_key = get_k8s_job_name(run_id, "count_letters")
    step_job_name = f"dagster-step-{step_job_key}"

    step_pods = DagsterKubernetesClient.production_client().get_pods_in_job(
        job_name=step_job_name, namespace=user_code_namespace_for_k8s_run_launcher
    )

    assert len(step_pods) == 1

    step_pod = step_pods[0]

    assert len(step_pod.spec.containers) == 1, str(step_pod)

    labels = step_pod.metadata.labels
    assert labels["run_launcher_label_key"] == "run_launcher_label_value"
    assert labels["executor_label_key"] == "executor_label_value"

    env_from = step_pod.spec.containers[0].env_from

    config_map_names = {env.config_map_ref.name for env in env_from if env.config_map_ref}
    secret_names = {env.secret_ref.name for env in env_from if env.secret_ref}

    # Run launcher secrets and config maps included
    assert TEST_SECRET_NAME in secret_names
    assert TEST_CONFIGMAP_NAME in config_map_names

    # Executor secrets and config maps included
    assert TEST_OTHER_SECRET_NAME in secret_names
    assert TEST_OTHER_CONFIGMAP_NAME in config_map_names

    image_pull_secrets_names = [secret.name for secret in step_pod.spec.image_pull_secrets]

    assert TEST_IMAGE_PULL_SECRET_NAME in image_pull_secrets_names
    assert TEST_OTHER_IMAGE_PULL_SECRET_NAME in image_pull_secrets_names


def _get_step_execution_events(events):
    return [
        event
        for event in events
        if ("Executing step" in event.message and "in Kubernetes job" in event.message)
    ]


def _launch_executor_run(
    webserver_url: str,
    run_config: Mapping[str, Any],
    dagster_instance_for_k8s_run_launcher: DagsterInstance,
    user_code_namespace_for_k8s_run_launcher: str,
    job_name: str = "demo_job_k8s",
    num_steps: int = 2,
):
    run_id = launch_run_over_graphql(webserver_url, run_config=run_config, job_name=job_name)

    result = wait_for_job_and_get_raw_logs(
        job_name=f"dagster-run-{run_id}", namespace=user_code_namespace_for_k8s_run_launcher
    )

    assert "RUN_SUCCESS" in result, f"no match, result: {result}"

    updated_run = dagster_instance_for_k8s_run_launcher.get_run_by_id(run_id)
    assert updated_run.tags[DOCKER_IMAGE_TAG] == get_test_project_docker_image()  # type: ignore  # (possible none)

    events = dagster_instance_for_k8s_run_launcher.all_logs(run_id)
    assert len(_get_step_execution_events(events)) == num_steps

    return run_id


@pytest.mark.integration
def test_k8s_run_launcher_image_from_origin(
    dagster_instance_for_k8s_run_launcher,
    user_code_namespace_for_k8s_run_launcher,
    webserver_url_for_k8s_run_launcher,
):
    # Like the previous test, but the executor doesn't supply an image - it's pulled
    # from the origin on the run instead
    pods = DagsterKubernetesClient.production_client().core_api.list_namespaced_pod(
        namespace=user_code_namespace_for_k8s_run_launcher
    )
    celery_pod_names = [p.metadata.name for p in pods.items if "celery-workers" in p.metadata.name]
    check.invariant(not celery_pod_names)

    run_config = merge_dicts(
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env.yaml")),  # pyright: ignore[reportArgumentType]
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env_s3.yaml")),  # pyright: ignore[reportArgumentType]
        {
            "execution": {
                "config": {
                    "job_namespace": user_code_namespace_for_k8s_run_launcher,
                    "image_pull_policy": image_pull_policy(),
                }
            },
        },
    )

    job_name = "demo_job_k8s"

    run_id = launch_run_over_graphql(
        webserver_url_for_k8s_run_launcher, run_config=run_config, job_name=job_name
    )

    result = wait_for_job_and_get_raw_logs(
        job_name=f"dagster-run-{run_id}", namespace=user_code_namespace_for_k8s_run_launcher
    )

    assert "RUN_SUCCESS" in result, f"no match, result: {result}"

    updated_run = dagster_instance_for_k8s_run_launcher.get_run_by_id(run_id)
    assert updated_run.tags[DOCKER_IMAGE_TAG] == get_test_project_docker_image()


@pytest.mark.integration
def test_k8s_run_launcher_terminate(
    dagster_instance_for_k8s_run_launcher,
    user_code_namespace_for_k8s_run_launcher,
    dagster_docker_image,
    webserver_url_for_k8s_run_launcher,
):
    job_name = "slow_job_k8s"

    run_config = merge_dicts(
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env_s3.yaml")),  # pyright: ignore[reportArgumentType]
        {
            "execution": {
                "config": {
                    "job_namespace": user_code_namespace_for_k8s_run_launcher,
                    "job_image": dagster_docker_image,
                    "image_pull_policy": image_pull_policy(),
                }
            },
        },
    )

    run_id = launch_run_over_graphql(
        webserver_url_for_k8s_run_launcher,
        run_config=run_config,
        job_name=job_name,
    )

    DagsterKubernetesClient.production_client().wait_for_job(
        job_name=f"dagster-run-{run_id}", namespace=user_code_namespace_for_k8s_run_launcher
    )
    timeout = datetime.timedelta(0, 30)
    start_time = datetime.datetime.now()
    while True:
        assert datetime.datetime.now() < start_time + timeout, "Timed out waiting for can_terminate"
        if can_terminate_run_over_graphql(webserver_url_for_k8s_run_launcher, run_id):
            break
        time.sleep(5)

    terminate_run_over_graphql(webserver_url_for_k8s_run_launcher, run_id=run_id)

    start_time = datetime.datetime.now()
    dagster_run = None
    while True:
        assert datetime.datetime.now() < start_time + timeout, "Timed out waiting for termination"
        dagster_run = dagster_instance_for_k8s_run_launcher.get_run_by_id(run_id)
        if dagster_run.status == DagsterRunStatus.CANCELED:
            break

        time.sleep(5)

    # useful to have logs here, because the worker pods get deleted
    print(dagster_instance_for_k8s_run_launcher.all_logs(run_id))  # noqa: T201

    assert dagster_run.status == DagsterRunStatus.CANCELED

    assert not can_terminate_run_over_graphql(webserver_url_for_k8s_run_launcher, run_id)


@pytest.mark.integration
def test_k8s_executor_resource_requirements(
    dagster_instance_for_k8s_run_launcher,
    user_code_namespace_for_k8s_run_launcher,
    dagster_docker_image,
    webserver_url_for_k8s_run_launcher,
):
    # sanity check that we have a K8sRunLauncher
    pods = DagsterKubernetesClient.production_client().core_api.list_namespaced_pod(
        namespace=user_code_namespace_for_k8s_run_launcher
    )
    celery_pod_names = [p.metadata.name for p in pods.items if "celery-workers" in p.metadata.name]
    check.invariant(not celery_pod_names)

    run_config = merge_dicts(
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env_s3.yaml")),  # pyright: ignore[reportArgumentType]
        {
            "execution": {
                "config": {
                    "job_namespace": user_code_namespace_for_k8s_run_launcher,
                    "job_image": dagster_docker_image,
                    "image_pull_policy": image_pull_policy(),
                }
            },
        },
    )

    job_name = "resources_limit_job_k8s"

    run_id = launch_run_over_graphql(
        webserver_url_for_k8s_run_launcher,
        run_config=run_config,
        job_name=job_name,
    )

    result = wait_for_job_and_get_raw_logs(
        job_name=f"dagster-run-{run_id}", namespace=user_code_namespace_for_k8s_run_launcher
    )

    assert "RUN_SUCCESS" in result, f"no match, result: {result}"

    updated_run = dagster_instance_for_k8s_run_launcher.get_run_by_id(run_id)
    assert updated_run.tags[DOCKER_IMAGE_TAG] == get_test_project_docker_image()


def _does_namespaced_job_exist(job_name: str, namespace: str) -> bool:
    try:
        DagsterKubernetesClient.production_client().batch_api.read_namespaced_job(
            name=job_name, namespace=namespace
        )
        return True
    except kubernetes.client.rest.ApiException as e:
        if e.status == 404:
            return False
        raise


def _does_namespaced_pod_exist(pod_name: str, namespace: str) -> bool:
    try:
        DagsterKubernetesClient.production_client().core_api.read_namespaced_pod(
            name=pod_name, namespace=namespace
        )
        return True
    except kubernetes.client.rest.ApiException as e:
        if e.status == 404:
            return False
        raise


def _does_pod_in_job_exist(job_name: str, namespace: str) -> bool:
    try:
        pods = DagsterKubernetesClient.production_client().get_pods_in_job(
            job_name=job_name, namespace=namespace
        )
        return len(pods) > 0
    except kubernetes.client.rest.ApiException as e:
        if e.status == 404:
            return False
        raise


@pytest.mark.integration
def test_k8s_executor_owner_references_garbage_collection(
    dagster_instance_for_k8s_run_launcher,
    user_code_namespace_for_k8s_run_launcher,
    dagster_docker_image,
    webserver_url_for_k8s_run_launcher,
):
    """Test that owner references are properly set when enable_owner_references is True, and that owner references properly
    allow for garbage collection of the step job and step pod when a run pod is deleted.
    """
    run_config = merge_dicts(
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env_s3.yaml")),  # pyright: ignore[reportArgumentType]
        {
            "execution": {
                "config": {
                    "job_namespace": user_code_namespace_for_k8s_run_launcher,
                    "job_image": dagster_docker_image,
                    "image_pull_policy": image_pull_policy(),
                    "enable_owner_references": True,
                }
            },
        },
    )

    # Job in question runs indefinitely, but we'll clean up the step once the run pod is deleted
    run_id = launch_run_over_graphql(
        webserver_url_for_k8s_run_launcher,
        run_config=run_config,
        job_name="spin_forever_job_k8s",
    )

    run_job_name = f"dagster-run-{run_id}"
    DagsterKubernetesClient.production_client().wait_for_job(
        job_name=run_job_name, namespace=user_code_namespace_for_k8s_run_launcher
    )

    run_pods = DagsterKubernetesClient.production_client().get_pods_in_job(
        job_name=run_job_name, namespace=user_code_namespace_for_k8s_run_launcher
    )
    assert len(run_pods) == 1
    run_pod = run_pods[0]

    step_job_key = get_k8s_job_name(run_id, "spin_forever_op")
    step_job_name = f"dagster-step-{step_job_key}"

    timeout = datetime.timedelta(0, 30)
    start_time = datetime.datetime.now()
    while True:
        assert datetime.datetime.now() < start_time + timeout, (
            "Timed out waiting for step job creation"
        )
        if _does_namespaced_job_exist(
            step_job_name, user_code_namespace_for_k8s_run_launcher
        ) and _does_pod_in_job_exist(step_job_name, user_code_namespace_for_k8s_run_launcher):
            break
        time.sleep(1)
    step_job = DagsterKubernetesClient.production_client().batch_api.read_namespaced_job(
        name=step_job_name, namespace=user_code_namespace_for_k8s_run_launcher
    )
    step_pods = DagsterKubernetesClient.production_client().get_pods_in_job(
        job_name=step_job_name, namespace=user_code_namespace_for_k8s_run_launcher
    )
    assert len(step_pods) == 1
    step_pod = step_pods[0]

    # Verify that the step job has an owner reference to the run pod
    step_job_owner_references = step_job.metadata.owner_references
    assert step_job_owner_references is not None

    pod_owner_ref = next((ref for ref in step_job_owner_references if ref.kind == "Pod"), None)
    assert pod_owner_ref is not None, "Step job should have an owner reference to a Pod"
    assert pod_owner_ref.name == run_pod.metadata.name, (
        f"Step job owner reference should point to run pod {run_pod.metadata.name}, but points to {pod_owner_ref.name}"
    )
    assert pod_owner_ref.uid == run_pod.metadata.uid, (
        "Step job owner reference UID should match run pod UID"
    )

    # Kill the run pod and wait for it to be deleted
    DagsterKubernetesClient.production_client().core_api.delete_namespaced_pod(
        name=run_pod.metadata.name, namespace=user_code_namespace_for_k8s_run_launcher
    )
    timeout = datetime.timedelta(0, 30)
    start_time = datetime.datetime.now()
    while True:
        assert datetime.datetime.now() < start_time + timeout, (
            "Timed out waiting for run pod deletion"
        )
        if not _does_namespaced_pod_exist(
            run_pod.metadata.name, user_code_namespace_for_k8s_run_launcher
        ):
            break
        time.sleep(1)

    # Wait for the step job and pod to be garbage collected
    timeout = datetime.timedelta(0, 120)
    start_time = datetime.datetime.now()
    while True:
        assert datetime.datetime.now() < start_time + timeout, (
            "Timed out waiting for step job garbage collection"
        )
        if not _does_namespaced_job_exist(
            step_job_name, user_code_namespace_for_k8s_run_launcher
        ) and not _does_namespaced_pod_exist(
            step_pod.metadata.name, user_code_namespace_for_k8s_run_launcher
        ):
            break
        time.sleep(1)


@pytest.mark.integration
def test_k8s_executor_owner_references_disabled(
    dagster_instance_for_k8s_run_launcher,
    user_code_namespace_for_k8s_run_launcher,
    dagster_docker_image,
    webserver_url_for_k8s_run_launcher,
):
    """Test that owner references are NOT set when enable_owner_references is False, and that garbage collection does NOT happen when the run pod is deleted."""
    run_config = merge_dicts(
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env_s3.yaml")),  # pyright: ignore[reportArgumentType]
        {
            "execution": {
                "config": {
                    "job_namespace": user_code_namespace_for_k8s_run_launcher,
                    "job_image": dagster_docker_image,
                    "image_pull_policy": image_pull_policy(),
                    "enable_owner_references": False,
                }
            },
        },
    )

    # Job in question runs indefinitely, but we'll verify that step resources persist when run pod is deleted
    run_id = launch_run_over_graphql(
        webserver_url_for_k8s_run_launcher,
        run_config=run_config,
        job_name="spin_forever_job_k8s",
    )

    run_job_name = f"dagster-run-{run_id}"
    DagsterKubernetesClient.production_client().wait_for_job(
        job_name=run_job_name, namespace=user_code_namespace_for_k8s_run_launcher
    )

    run_pods = DagsterKubernetesClient.production_client().get_pods_in_job(
        job_name=run_job_name, namespace=user_code_namespace_for_k8s_run_launcher
    )
    assert len(run_pods) == 1
    run_pod = run_pods[0]

    step_job_key = get_k8s_job_name(run_id, "spin_forever_op")
    step_job_name = f"dagster-step-{step_job_key}"

    timeout = datetime.timedelta(0, 30)
    start_time = datetime.datetime.now()
    while True:
        assert datetime.datetime.now() < start_time + timeout, (
            "Timed out waiting for step job creation"
        )
        if _does_namespaced_job_exist(
            step_job_name, user_code_namespace_for_k8s_run_launcher
        ) and _does_pod_in_job_exist(step_job_name, user_code_namespace_for_k8s_run_launcher):
            break
        time.sleep(1)
    step_job = DagsterKubernetesClient.production_client().batch_api.read_namespaced_job(
        name=step_job_name, namespace=user_code_namespace_for_k8s_run_launcher
    )
    step_pods = DagsterKubernetesClient.production_client().get_pods_in_job(
        job_name=step_job_name, namespace=user_code_namespace_for_k8s_run_launcher
    )
    assert len(step_pods) == 1
    step_pod = step_pods[0]

    step_job = DagsterKubernetesClient.production_client().batch_api.read_namespaced_job(
        name=step_job_name, namespace=user_code_namespace_for_k8s_run_launcher
    )

    # Verify that the step job does NOT have owner references
    step_job_owner_references = step_job.metadata.owner_references
    assert step_job_owner_references is None or len(step_job_owner_references) == 0

    # Kill the run pod and wait for it to be deleted
    DagsterKubernetesClient.production_client().core_api.delete_namespaced_pod(
        name=run_pod.metadata.name, namespace=user_code_namespace_for_k8s_run_launcher
    )
    timeout = datetime.timedelta(0, 30)
    start_time = datetime.datetime.now()
    while True:
        assert datetime.datetime.now() < start_time + timeout, (
            "Timed out waiting for run pod deletion"
        )
        if not _does_namespaced_pod_exist(
            run_pod.metadata.name, user_code_namespace_for_k8s_run_launcher
        ):
            break
        time.sleep(1)

    # Wait a bit and verify that the step job and pod are NOT garbage collected
    time.sleep(10)
    assert _does_namespaced_job_exist(step_job_name, user_code_namespace_for_k8s_run_launcher), (
        "Step job should NOT be garbage collected when owner references are disabled"
    )
    assert _does_namespaced_pod_exist(
        step_pod.metadata.name, user_code_namespace_for_k8s_run_launcher
    ), "Step pod should NOT be garbage collected when owner references are disabled"


@pytest.mark.integration
def test_execute_on_k8s_retry_job(
    dagster_instance_for_k8s_run_launcher,
    user_code_namespace_for_k8s_run_launcher,
    dagster_docker_image,
    webserver_url_for_k8s_run_launcher,
):
    run_config = merge_dicts(
        load_yaml_from_path(os.path.join(get_test_project_environments_path(), "env_s3.yaml")),  # pyright: ignore[reportArgumentType]
        {
            "execution": {
                "config": {
                    "job_namespace": user_code_namespace_for_k8s_run_launcher,
                    "job_image": dagster_docker_image,
                    "image_pull_policy": image_pull_policy(),
                }
            },
        },
    )

    job_name = "retry_job_k8s"

    run_id = launch_run_over_graphql(
        webserver_url_for_k8s_run_launcher,
        run_config=run_config,
        job_name=job_name,
    )

    result = wait_for_job_and_get_raw_logs(
        job_name=f"dagster-run-{run_id}", namespace=user_code_namespace_for_k8s_run_launcher
    )

    assert "RUN_SUCCESS" in result, f"no match, result: {result}"

    stats = dagster_instance_for_k8s_run_launcher.get_run_stats(run_id)
    assert stats.steps_succeeded == 1

    all_logs = dagster_instance_for_k8s_run_launcher.all_logs(run_id)

    assert DagsterEventType.STEP_START in [
        event.dagster_event.event_type for event in all_logs if event.is_dagster_event
    ]

    assert DagsterEventType.STEP_UP_FOR_RETRY in [
        event.dagster_event.event_type for event in all_logs if event.is_dagster_event
    ]

    assert DagsterEventType.STEP_RESTARTED in [
        event.dagster_event.event_type for event in all_logs if event.is_dagster_event
    ]

    assert DagsterEventType.STEP_SUCCESS in [
        event.dagster_event.event_type for event in all_logs if event.is_dagster_event
    ]
