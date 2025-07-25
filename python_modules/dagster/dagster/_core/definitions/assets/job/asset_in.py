from collections.abc import Mapping, Sequence
from typing import NamedTuple, Optional, Union

import dagster._check as check
from dagster._annotations import PublicAttr, public
from dagster._core.definitions.events import (
    AssetKey,
    CoercibleToAssetKey,
    CoercibleToAssetKeyPrefix,
)
from dagster._core.definitions.input import NoValueSentinel
from dagster._core.definitions.metadata import ArbitraryMetadataMapping
from dagster._core.definitions.partitions.mapping import PartitionMapping
from dagster._core.types.dagster_type import DagsterType, resolve_dagster_type


@public
class AssetIn(
    NamedTuple(
        "_AssetIn",
        [
            ("key", PublicAttr[Optional[AssetKey]]),
            ("metadata", PublicAttr[Optional[ArbitraryMetadataMapping]]),
            ("key_prefix", PublicAttr[Optional[Sequence[str]]]),
            ("input_manager_key", PublicAttr[Optional[str]]),
            ("partition_mapping", PublicAttr[Optional[PartitionMapping]]),
            ("dagster_type", PublicAttr[Union[DagsterType, type[NoValueSentinel]]]),
        ],
    )
):
    """Defines an asset dependency.

    Args:
        key_prefix (Optional[Union[str, Sequence[str]]]): If provided, the asset's key is the
            concatenation of the key_prefix and the input name. Only one of the "key_prefix" and
            "key" arguments should be provided.
        key (Optional[Union[str, Sequence[str], AssetKey]]): The asset's key. Only one of the
            "key_prefix" and "key" arguments should be provided.
        metadata (Optional[Dict[str, Any]]): A dict of the metadata for the input.
            For example, if you only need a subset of columns from an upstream table, you could
            include that in metadata and the IO manager that loads the upstream table could use the
            metadata to determine which columns to load.
        partition_mapping (Optional[PartitionMapping]): Defines what partitions to depend on in
            the upstream asset. If not provided, defaults to the default partition mapping for the
            partitions definition, which is typically maps partition keys to the same partition keys
            in upstream assets.
        dagster_type (DagsterType): Allows specifying type validation functions that
            will be executed on the input of the decorated function before it runs.
    """

    def __new__(
        cls,
        key: Optional[CoercibleToAssetKey] = None,
        metadata: Optional[ArbitraryMetadataMapping] = None,
        key_prefix: Optional[CoercibleToAssetKeyPrefix] = None,
        input_manager_key: Optional[str] = None,
        partition_mapping: Optional[PartitionMapping] = None,
        dagster_type: Union[DagsterType, type] = NoValueSentinel,
    ):
        if isinstance(key_prefix, str):
            key_prefix = [key_prefix]

        check.invariant(
            not (key and key_prefix), "key and key_prefix cannot both be set on AssetIn"
        )

        return super().__new__(
            cls,
            key=AssetKey.from_coercible(key) if key is not None else None,
            metadata=check.opt_inst_param(metadata, "metadata", Mapping),
            key_prefix=check.opt_list_param(key_prefix, "key_prefix", of_type=str),
            input_manager_key=check.opt_str_param(input_manager_key, "input_manager_key"),
            partition_mapping=check.opt_inst_param(
                partition_mapping, "partition_mapping", PartitionMapping
            ),
            dagster_type=(
                NoValueSentinel
                if dagster_type is NoValueSentinel
                else resolve_dagster_type(dagster_type)
            ),
        )

    @classmethod
    def from_coercible(cls, coercible: "CoercibleToAssetIn") -> "AssetIn":
        return coercible if isinstance(coercible, AssetIn) else AssetIn(key=coercible)

    def resolve_key(self, input_name: str) -> AssetKey:
        return self.key or AssetKey.from_coercible(input_name).with_prefix(self.key_prefix or [])


CoercibleToAssetIn = Union[AssetIn, CoercibleToAssetKey]
